`timescale 1ns / 1ps
//
// reverb.sv
//
// Schroeder/Moorer-style reverb used by tools/wavsim/refmodels/reverb.py:
//
//     four parallel damped feedback comb filters
//                       |
//                       v
//                 average of 4
//                       |
//                       v
//                  all-pass #1
//                       |
//                       v
//                  all-pass #2
//                       |
//                       v
//                  dry / wet mix
//
// The delay lengths are the same as the Python reference model at 48 kHz.
// Internal delay-line samples are kept as signed Q23 values with 32 total bits
// (8 bits of headroom above the 24-bit external audio format).  The extra
// headroom prevents the comb recirculation from wrapping while still mapping
// efficiently into the Zybo's 36-kbit BRAMs.
//
// One input sample takes four processing clocks after it is accepted:
// combs -> allpass 1 -> allpass 2 -> mix/output.  The project gives this effect
// 32 clocks per input sample in configs/effects/reverb.json, so there is ample
// timing margin and no back-pressure is required.
//
module reverb (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                     decay,    // Comb feedback. Higher = longer tail.
    input  logic [15:0]                     damping,  // Lowpass inside the comb loop, so highs decay first.
    input  logic [15:0]                     mix,      // Dry/wet balance.

    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    //constants

    localparam int C0_LEN  = 1687;
    localparam int C1_LEN  = 1801;
    localparam int C2_LEN  = 2113;
    localparam int C3_LEN  = 2311;
    localparam int AP1_LEN = 241;
    localparam int AP2_LEN = 83;

    // The floating-point model clamps decay to 0.98 and damping to 0.99.
    // Values below are round(0.98*65535) and round(0.99*65535).
    localparam logic [15:0] DECAY_MAX = 16'd64224;
    localparam logic [15:0] DAMP_MAX  = 16'd64880;

    localparam int C0_AW  = $clog2(C0_LEN);
    localparam int C1_AW  = $clog2(C1_LEN);
    localparam int C2_AW  = $clog2(C2_LEN);
    localparam int C3_AW  = $clog2(C3_LEN);
    localparam int AP1_AW = $clog2(AP1_LEN);
    localparam int AP2_AW = $clog2(AP2_LEN);

    localparam int C0_CW  = $clog2(C0_LEN  + 1);
    localparam int C1_CW  = $clog2(C1_LEN  + 1);
    localparam int C2_CW  = $clog2(C2_LEN  + 1);
    localparam int C3_CW  = $clog2(C3_LEN  + 1);
    localparam int AP1_CW = $clog2(AP1_LEN + 1);
    localparam int AP2_CW = $clog2(AP2_LEN + 1);

    //helper functions

    // Multiply a signed Q23 value by an unsigned Q16 coefficient and return
    // signed Q23.  32x17 -> 49 bits.  Adding 0.5 LSB before >>> 16 rounds to
    // nearest rather than accumulating truncation bias in the feedback loops.
    function automatic logic signed [31:0] mul_q16_32(
        input logic signed [31:0] x,
        input logic        [15:0] k
    );
        logic signed [48:0] product;
        begin
            product    = x * $signed({1'b0, k});
            mul_q16_32 = (product + 49'sd32768) >>> 16;
        end
    endfunction

    // (1-k)*a + k*b using the same 65535 endpoint convention used elsewhere in
    // this repo.  This is used for the one-pole damping interpolation.
    function automatic logic signed [31:0] blend_q16_32(
        input logic signed [31:0] a,
        input logic signed [31:0] b,
        input logic        [15:0] k
    );
        logic        [15:0] ka;
        logic signed [48:0] pa;
        logic signed [48:0] pb;
        logic signed [49:0] sum;
        begin
            ka = 16'hFFFF - k;
            pa = a * $signed({1'b0, ka});
            pb = b * $signed({1'b0, k});
            sum = {pa[48], pa} + {pb[48], pb};
            blend_q16_32 = (sum + 50'sd32768) >>> 16;
        end
    endfunction

    function automatic logic signed [31:0] sat32(
        input logic signed [32:0] x
    );
        begin
            if (x > 33'sd2147483647)
                sat32 = 32'sh7FFF_FFFF;
            else if (x < -33'sd2147483648)
                sat32 = 32'sh8000_0000;
            else
                sat32 = x[31:0];
        end
    endfunction

    function automatic logic signed [23:0] sat24_from32(
        input logic signed [31:0] x
    );
        begin
            if (x > 32'sd8388607)
                sat24_from32 = 24'sh7F_FFFF;
            else if (x < -32'sd8388608)
                sat24_from32 = 24'sh80_0000;
            else
                sat24_from32 = x[23:0];
        end
    endfunction

    //sequencer

    typedef enum logic [2:0] {
        S_IDLE,
        S_COMB,
        S_AP1,
        S_AP2,
        S_MIX
    } state_t;

    state_t state = S_IDLE;

    logic signed [31:0] sample_x = '0;
    logic        [15:0] decay_x  = '0;
    logic        [15:0] damping_x = '0;
    logic        [15:0] mix_x    = '0;

    //comb memories

    // The four combs run in parallel.  Each buffer stores y[n].  For damping we
    // need y[n-L] and y[n-L-1]; because each pointer advances by exactly one
    // sample, y[n-L-1] is simply the delayed value read on the previous sample.

    (* ram_style = "block" *) logic signed [31:0] comb0_mem [0:C0_LEN-1];
    (* ram_style = "block" *) logic signed [31:0] comb1_mem [0:C1_LEN-1];
    (* ram_style = "block" *) logic signed [31:0] comb2_mem [0:C2_LEN-1];
    (* ram_style = "block" *) logic signed [31:0] comb3_mem [0:C3_LEN-1];

    logic [C0_AW-1:0] c0_ptr = '0;
    logic [C1_AW-1:0] c1_ptr = '0;
    logic [C2_AW-1:0] c2_ptr = '0;
    logic [C3_AW-1:0] c3_ptr = '0;

    logic [C0_CW-1:0] c0_filled = '0;
    logic [C1_CW-1:0] c1_filled = '0;
    logic [C2_CW-1:0] c2_filled = '0;
    logic [C3_CW-1:0] c3_filled = '0;

    logic signed [31:0] c0_rd = '0;
    logic signed [31:0] c1_rd = '0;
    logic signed [31:0] c2_rd = '0;
    logic signed [31:0] c3_rd = '0;

    logic signed [31:0] c0_prev_delayed = '0;
    logic signed [31:0] c1_prev_delayed = '0;
    logic signed [31:0] c2_prev_delayed = '0;
    logic signed [31:0] c3_prev_delayed = '0;

    wire signed [31:0] c0_delayed = (c0_filled == C0_CW'(C0_LEN)) ? c0_rd : 32'sd0;
    wire signed [31:0] c1_delayed = (c1_filled == C1_CW'(C1_LEN)) ? c1_rd : 32'sd0;
    wire signed [31:0] c2_delayed = (c2_filled == C2_CW'(C2_LEN)) ? c2_rd : 32'sd0;
    wire signed [31:0] c3_delayed = (c3_filled == C3_CW'(C3_LEN)) ? c3_rd : 32'sd0;

    wire signed [31:0] c0_damped = blend_q16_32(c0_delayed, c0_prev_delayed, damping_x);
    wire signed [31:0] c1_damped = blend_q16_32(c1_delayed, c1_prev_delayed, damping_x);
    wire signed [31:0] c2_damped = blend_q16_32(c2_delayed, c2_prev_delayed, damping_x);
    wire signed [31:0] c3_damped = blend_q16_32(c3_delayed, c3_prev_delayed, damping_x);

    wire signed [31:0] c0_fb = mul_q16_32(c0_damped, decay_x);
    wire signed [31:0] c1_fb = mul_q16_32(c1_damped, decay_x);
    wire signed [31:0] c2_fb = mul_q16_32(c2_damped, decay_x);
    wire signed [31:0] c3_fb = mul_q16_32(c3_damped, decay_x);

    wire signed [32:0] c0_sum_wide = {sample_x[31], sample_x} + {c0_fb[31], c0_fb};
    wire signed [32:0] c1_sum_wide = {sample_x[31], sample_x} + {c1_fb[31], c1_fb};
    wire signed [32:0] c2_sum_wide = {sample_x[31], sample_x} + {c2_fb[31], c2_fb};
    wire signed [32:0] c3_sum_wide = {sample_x[31], sample_x} + {c3_fb[31], c3_fb};

    wire signed [31:0] c0_next = sat32(c0_sum_wide);
    wire signed [31:0] c1_next = sat32(c1_sum_wide);
    wire signed [31:0] c2_next = sat32(c2_sum_wide);
    wire signed [31:0] c3_next = sat32(c3_sum_wide);

    wire signed [33:0] comb_sum =
          {{2{c0_next[31]}}, c0_next}
        + {{2{c1_next[31]}}, c1_next}
        + {{2{c2_next[31]}}, c2_next}
        + {{2{c3_next[31]}}, c3_next};

    wire signed [31:0] comb_average = comb_sum >>> 2;
    logic signed [31:0] wet_comb = '0;

    // Synchronous read, synchronous write, read-first.  The read value used by
    // S_COMB was fetched while the state machine was accepting/holding the
    // current sample.  During S_COMB the old entry is read again and c*_next is
    // written into the same address; the pointer advances only after that edge.
    always_ff @(posedge clk) begin
        c0_rd <= comb0_mem[c0_ptr];
        c1_rd <= comb1_mem[c1_ptr];
        c2_rd <= comb2_mem[c2_ptr];
        c3_rd <= comb3_mem[c3_ptr];

        if (state == S_COMB) begin
            comb0_mem[c0_ptr] <= c0_next;
            comb1_mem[c1_ptr] <= c1_next;
            comb2_mem[c2_ptr] <= c2_next;
            comb3_mem[c3_ptr] <= c3_next;
        end
    end

    //all-pass stage 1

    // Schroeder all-pass with g = 0.5, implemented with one delay line:
    //   v[n] = x[n] + g*v[n-L]
    //   y[n] = v[n-L] - g*v[n]
    // which gives H(z) = (z^-L - g) / (1 - g*z^-L), exactly matching the
    // scipy lfilter form in the reference model.

    (* ram_style = "block" *) logic signed [31:0] ap1_mem [0:AP1_LEN-1];
    logic [AP1_AW-1:0] ap1_ptr = '0;
    logic [AP1_CW-1:0] ap1_filled = '0;
    logic signed [31:0] ap1_rd = '0;

    wire signed [31:0] ap1_delayed = (ap1_filled == AP1_CW'(AP1_LEN)) ? ap1_rd : 32'sd0;
    wire signed [31:0] ap1_half_delayed = mul_q16_32(ap1_delayed, 16'h8000);
    wire signed [32:0] ap1_v_wide = {wet_comb[31], wet_comb} + {ap1_half_delayed[31], ap1_half_delayed};
    wire signed [31:0] ap1_v_next = sat32(ap1_v_wide);
    wire signed [31:0] ap1_half_v = mul_q16_32(ap1_v_next, 16'h8000);
    wire signed [32:0] ap1_y_wide = {ap1_delayed[31], ap1_delayed} - {ap1_half_v[31], ap1_half_v};
    wire signed [31:0] ap1_y_next = sat32(ap1_y_wide);
    logic signed [31:0] wet_ap1 = '0;

    always_ff @(posedge clk) begin
        ap1_rd <= ap1_mem[ap1_ptr];
        if (state == S_AP1)
            ap1_mem[ap1_ptr] <= ap1_v_next;
    end

    //all-pass stage 2

    (* ram_style = "block" *) logic signed [31:0] ap2_mem [0:AP2_LEN-1];
    logic [AP2_AW-1:0] ap2_ptr = '0;
    logic [AP2_CW-1:0] ap2_filled = '0;
    logic signed [31:0] ap2_rd = '0;

    wire signed [31:0] ap2_delayed = (ap2_filled == AP2_CW'(AP2_LEN)) ? ap2_rd : 32'sd0;
    wire signed [31:0] ap2_half_delayed = mul_q16_32(ap2_delayed, 16'h8000);
    wire signed [32:0] ap2_v_wide = {wet_ap1[31], wet_ap1} + {ap2_half_delayed[31], ap2_half_delayed};
    wire signed [31:0] ap2_v_next = sat32(ap2_v_wide);
    wire signed [31:0] ap2_half_v = mul_q16_32(ap2_v_next, 16'h8000);
    wire signed [32:0] ap2_y_wide = {ap2_delayed[31], ap2_delayed} - {ap2_half_v[31], ap2_half_v};
    wire signed [31:0] ap2_y_next = sat32(ap2_y_wide);
    logic signed [31:0] wet_ap2 = '0;

    always_ff @(posedge clk) begin
        ap2_rd <= ap2_mem[ap2_ptr];
        if (state == S_AP2)
            ap2_mem[ap2_ptr] <= ap2_v_next;
    end

    //final mix

    wire signed [31:0] mixed_q23 = blend_q16_32(sample_x, wet_ap2, mix_x);

    //state machine

    always_ff @(posedge clk) begin
        sample_out_valid <= 1'b0;

        if (!rst_n) begin
            state            <= S_IDLE;
            sample_out       <= '0;
            sample_x         <= '0;
            decay_x          <= '0;
            damping_x        <= '0;
            mix_x            <= '0;
            wet_comb         <= '0;
            wet_ap1          <= '0;
            wet_ap2          <= '0;

            c0_ptr           <= '0;
            c1_ptr           <= '0;
            c2_ptr           <= '0;
            c3_ptr           <= '0;
            c0_filled        <= '0;
            c1_filled        <= '0;
            c2_filled        <= '0;
            c3_filled        <= '0;
            c0_prev_delayed  <= '0;
            c1_prev_delayed  <= '0;
            c2_prev_delayed  <= '0;
            c3_prev_delayed  <= '0;

            ap1_ptr          <= '0;
            ap1_filled       <= '0;
            ap2_ptr          <= '0;
            ap2_filled       <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (sample_in_valid) begin
                        // Sign-extend the external Q0.23 sample into the internal
                        // Q23 format and freeze all controls for this sample.
                        sample_x  <= {{8{sample_in[23]}}, sample_in};
                        decay_x   <= (decay   > DECAY_MAX) ? DECAY_MAX : decay;
                        damping_x <= (damping > DAMP_MAX)  ? DAMP_MAX  : damping;
                        mix_x     <= mix;
                        state     <= S_COMB;
                    end
                end

                S_COMB: begin
                    wet_comb <= comb_average;

                    c0_prev_delayed <= c0_delayed;
                    c1_prev_delayed <= c1_delayed;
                    c2_prev_delayed <= c2_delayed;
                    c3_prev_delayed <= c3_delayed;

                    c0_ptr <= (c0_ptr == C0_AW'(C0_LEN-1)) ? '0 : c0_ptr + 1'b1;
                    c1_ptr <= (c1_ptr == C1_AW'(C1_LEN-1)) ? '0 : c1_ptr + 1'b1;
                    c2_ptr <= (c2_ptr == C2_AW'(C2_LEN-1)) ? '0 : c2_ptr + 1'b1;
                    c3_ptr <= (c3_ptr == C3_AW'(C3_LEN-1)) ? '0 : c3_ptr + 1'b1;

                    if (c0_filled < C0_CW'(C0_LEN)) c0_filled <= c0_filled + 1'b1;
                    if (c1_filled < C1_CW'(C1_LEN)) c1_filled <= c1_filled + 1'b1;
                    if (c2_filled < C2_CW'(C2_LEN)) c2_filled <= c2_filled + 1'b1;
                    if (c3_filled < C3_CW'(C3_LEN)) c3_filled <= c3_filled + 1'b1;

                    state <= S_AP1;
                end

                S_AP1: begin
                    wet_ap1 <= ap1_y_next;
                    ap1_ptr <= (ap1_ptr == AP1_AW'(AP1_LEN-1)) ? '0 : ap1_ptr + 1'b1;
                    if (ap1_filled < AP1_CW'(AP1_LEN)) ap1_filled <= ap1_filled + 1'b1;
                    state <= S_AP2;
                end

                S_AP2: begin
                    wet_ap2 <= ap2_y_next;
                    ap2_ptr <= (ap2_ptr == AP2_AW'(AP2_LEN-1)) ? '0 : ap2_ptr + 1'b1;
                    if (ap2_filled < AP2_CW'(AP2_LEN)) ap2_filled <= ap2_filled + 1'b1;
                    state <= S_MIX;
                end

                S_MIX: begin
                    sample_out       <= sat24_from32(mixed_q23);
                    sample_out_valid <= 1'b1;
                    state            <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

`timescale 1ns / 1ps
`include "chorus_sine_table.svh"
//
// chorus.sv
//
// An LFO-modulated short delay mixed back with the dry signal. The wet copy is
// continuously slightly sharp or flat against the dry one, and that detuning is
// the whole effect.
//
// Two things have to be right or it sounds wrong rather than subtly different:
//
//   1. The read pointer moves in *fractional* steps. Truncating the address to
//      whole samples steps audibly and sounds gritty, so the delay is carried
//      in Q12 (1/4096 sample) and the output is linearly interpolated between
//      two adjacent buffer entries.
//   2. The LFO itself is interpolated. A 1024-point table read without
//      interpolation would hold the delay constant for tens of samples and then
//      jump by most of a sample, which is the same zipper artefact one level up.
//      Interpolating between table points makes the sweep continuous.
//
// tools/wavsim/refmodels/chorus.py is the specification and interpolates the
// delay line the same way, so the two are directly comparable.
//
// Signal path, one pass per input sample:
//
//   x -> circular buffer
//        phase accumulator -> sine ROM + interpolation -> lfo
//          -> delay = (base_ms + depth_ms * lfo) samples, Q12
//             -> read buf[n - floor(delay)] and buf[n - floor(delay) - 1]
//                -> interpolate -> wet
//                   -> out = x*(1-mix) + wet*mix
//
// There are ~32 clocks between samples and this takes 13, so both memories are
// read one address at a time. That keeps the sample buffer to a simple
// dual-port BRAM and lets the sine table infer a BRAM too, instead of the ~380
// LUTs a combinational two-port read of it would cost.
//
module chorus (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                     rate,      // LFO frequency, centi-hertz: 100 = 1.00 Hz
    input  logic [15:0]                     depth,     // sweep either side of base, 0.1 ms steps
    input  logic [15:0]                     mix,       // Q16 dry/wet, 0 = dry only
    input  logic [15:0]                     base_ms,   // centre delay, 0.1 ms steps

    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    // ---------------------------------------------------------------- sizing

    // Sized from the manifest's declared base_ms and depth ranges, rounded up
    // to a power of two so the circular address wraps by truncation. Widening
    // those ranges grows this buffer, so check the cost the generator prints.
    localparam int MAX_DELAY_SAMPLES = `CHORUS_MAX_DELAY_SAMPLES;
    localparam int ADDR_W            = $clog2(MAX_DELAY_SAMPLES);

    // Fractional bits used when interpolating the delay line: 1/4096 sample.
    localparam int FRAC_BITS = 12;
    localparam int FRAC_ONE  = 1 << FRAC_BITS;

    // The delay is carried with more fraction than the interpolation uses,
    // because the conversion constant cannot be exact: 0.1 ms is 4.8 samples at
    // 48 kHz, and 4.8 * 2^k is never a whole number. At Q12 the rounding offsets
    // a 12 ms delay by 0.006 samples, enough to show up against the reference
    // model at 1 kHz. At Q20 it costs 7.6e-6 samples, which does not.
    //
    // base_ms and depth get *separate* constants because the manifest is free
    // to give them different units, and it does. Sharing one constant here is
    // how this module once applied ten times the intended modulation.
    localparam int DELAY_Q                 = `CHORUS_DELAY_Q;
    localparam int DELAY_PER_BASE_UNIT     = `CHORUS_DELAY_PER_BASE_UNIT;
    localparam int DELAY_PER_DEPTH_UNIT    = `CHORUS_DELAY_PER_DEPTH_UNIT;

    // Phase step per centi-hertz, and the one number in this module that has to
    // be exactly right. An error here is a *rate* error, so the LFO drifts
    // further from the reference the longer the clip runs rather than settling
    // at some bounded offset.
    //
    // Two things are needed to get it: enough fractional bits in the constant,
    // and an accumulator that actually carries them. Truncating the increment
    // to a whole number of phase units throws the precision straight back away.
    // Hence a 48-bit accumulator with the sine index taken from its top bits.
    //
    // All three constants come from scripts/gen_sine_table.py. They were hand
    // computed once, and one of them was 60 ppm off; see that script.
    localparam int PHASE_W               = `CHORUS_PHASE_W;         // 32
    localparam int PHASE_INC_FRAC        = `CHORUS_PHASE_INC_FRAC;  // 16
    localparam int PHASE_ACC_W           = PHASE_W + PHASE_INC_FRAC;   // 48
    localparam int PHASE_INC_PER_CHZ_Q16 = `CHORUS_PHASE_INC_PER_CENTIHZ;

    // Sine ROM geometry, from the generated header.
    localparam int SINE_ENTRIES = `CHORUS_SINE_ENTRIES;   // 1024
    localparam int SINE_W       = `CHORUS_SINE_WIDTH;     // 24, Q23
    localparam int SINE_IDX_W   = $clog2(SINE_ENTRIES);   // 10
    localparam int SINE_FRAC_W  = 12;                     // bits below the index
    localparam int SINE_Q       = SINE_W - 1;             // 23

    // The delay can never be shorter than one sample: the buffer read is
    // registered, so sample n is not available to its own output. The reference
    // model applies the same floor. It only bites when depth > base_ms, which
    // is not a useful setting anyway.
    localparam longint MIN_DELAY_Q = longint'(1) <<< DELAY_Q;
    localparam longint MAX_DELAY_Q = (longint'(MAX_DELAY_SAMPLES) - 2) <<< DELAY_Q;

    // ------------------------------------------------------------- sine ROM

    // One full cycle, Q23. Generated by scripts/gen_sine_table.py because
    // Vivado does not accept $sin in synthesisable code; see that script.
    (* rom_style = "block" *)
    logic signed [SINE_W-1:0] sine_tab [0:SINE_ENTRIES-1];

    initial begin
        `CHORUS_SINE_INIT
    end

    logic [SINE_IDX_W-1:0]    sine_addr = '0;
    logic signed [SINE_W-1:0] sine_q    = '0;

    always_ff @(posedge clk) begin
        sine_q <= sine_tab[sine_addr];
    end

    // --------------------------------------------------------- sample buffer

    (* ram_style = "block" *)
    logic signed [23:0] sample_buf [0:MAX_DELAY_SAMPLES-1];

    initial begin
        for (int i = 0; i < MAX_DELAY_SAMPLES; i++) begin
            sample_buf[i] = 24'sd0;
        end
    end

    logic [ADDR_W-1:0]  wr_addr  = '0;
    logic [ADDR_W-1:0]  rd_addr  = '0;
    logic signed [23:0] rd_data  = '0;
    logic               buf_we   = 1'b0;
    logic signed [23:0] sample_x = '0;   // the dry sample currently being processed

    // One write port, one read port: a simple dual-port BRAM. delay_int is
    // always at least 1, so the read address never collides with the write.
    always_ff @(posedge clk) begin
        if (buf_we) sample_buf[wr_addr] <= sample_x;
        rd_data <= sample_buf[rd_addr];
    end

    // ------------------------------------------------------- datapath wiring

    logic [PHASE_ACC_W-1:0]    phase      = '0;   // Q16 below the 32-bit phase
    logic [SINE_FRAC_W-1:0]    sine_frac  = '0;
    logic signed [SINE_W-1:0]  sine_s0    = '0;
    logic signed [SINE_W-1:0]  sine_s1    = '0;
    logic signed [SINE_W:0]    lfo        = '0;   // Q23, -1.0 .. +1.0
    logic signed [39:0]        delay_q    = '0;
    logic [ADDR_W-1:0]         delay_int  = '0;
    logic [FRAC_BITS-1:0]      delay_frac = '0;
    logic signed [23:0]        s_near     = '0;
    logic signed [23:0]        s_far      = '0;
    logic signed [23:0]        wet        = '0;

    // rate * 58644152 needs 36 bits; it is accumulated at full Q16 precision.
    logic [PHASE_ACC_W-1:0] phase_inc;
    assign phase_inc = PHASE_ACC_W'(rate) * PHASE_ACC_W'(PHASE_INC_PER_CHZ_Q16);

    // LFO interpolation between the two table points.
    logic signed [SINE_W:0]           sine_diff;
    logic signed [SINE_W+SINE_FRAC_W:0] sine_step;
    logic signed [SINE_W:0]           lfo_next;
    assign sine_diff = (SINE_W+1)'(sine_s1) - (SINE_W+1)'(sine_s0);
    assign sine_step = sine_diff * $signed({1'b0, sine_frac});
    assign lfo_next  = (SINE_W+1)'(sine_s0) + (SINE_W+1)'(sine_step >>> SINE_FRAC_W);

    // delay = base_ms + depth_ms * lfo. Both are in the same 0.1 ms unit so
    // they share one scaling constant; the LFO only weights the depth term.
    // 40 bits carries the widest knob settings the manifest allows with room
    // to spare; the generator prints the reach these constants imply.
    logic signed [39:0] base_term;
    logic signed [39:0] depth_scaled;
    logic signed [63:0] depth_term;
    logic signed [39:0] delay_unclamped;

    assign base_term       = 40'($signed({1'b0, base_ms})) * DELAY_PER_BASE_UNIT;
    assign depth_scaled    = 40'($signed({1'b0, depth})) * DELAY_PER_DEPTH_UNIT;
    assign depth_term      = 64'(depth_scaled) * 64'(lfo);
    assign delay_unclamped = base_term + 40'(depth_term >>> SINE_Q);

    // Interpolation tap addresses. delay_int is clamped to MAX_DELAY_SAMPLES-2,
    // so both subtractions stay inside the buffer once the address truncates.
    logic [ADDR_W-1:0] addr_near;
    logic [ADDR_W-1:0] addr_far;
    assign addr_near = wr_addr - delay_int;
    assign addr_far  = wr_addr - delay_int - 1'b1;

    // Linear interpolation on the delay line. (FRAC_ONE - frac) + frac is
    // exactly FRAC_ONE, so this is a true convex combination of two 24-bit
    // samples and cannot overflow.
    logic signed [37:0] interp;
    assign interp = s_near * $signed({1'b0, (FRAC_BITS+1)'(FRAC_ONE - delay_frac)})
                  + s_far  * $signed({1'b0, (FRAC_BITS+1)'(delay_frac)});

    // Dry/wet, using the same 65535-vs-65536 convention as delay.sv. The
    // endpoint attenuation is one part in 65536; see docs/fixed_point.md.
    logic signed [40:0] mixed;
    assign mixed = sample_x * $signed({1'b0, (16'hFFFF - mix)})
                 + wet      * $signed({1'b0, mix});

    // ------------------------------------------------------------- sequencer

    typedef enum logic [3:0] {
        S_IDLE,
        S_LFO_ADDR1,   // ask for the second table point
        S_LFO_TAKE0,   // first point lands in sine_q
        S_LFO_TAKE1,   // second point lands in sine_q
        S_LFO_INTERP,
        S_DELAY,
        S_SPLIT,
        S_ADDR_NEAR,
        S_ADDR_FAR,
        S_TAKE_NEAR,
        S_TAKE_FAR,
        S_INTERP,
        S_MIX
    } state_t;

    state_t state = S_IDLE;

    always_ff @(posedge clk) begin
        buf_we           <= 1'b0;
        sample_out_valid <= 1'b0;

        if (!rst_n) begin
            state      <= S_IDLE;
            phase      <= '0;
            wr_addr    <= '0;
            sample_out <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (sample_in_valid) begin
                        sample_x <= sample_in;
                        buf_we   <= 1'b1;   // writes sample_x at wr_addr next cycle

                        // Split the *current* phase, so sample n uses
                        // sin(2*pi*rate*n/fs) and the first sample sees phase 0.
                        // The reference model starts the same way.
                        sine_addr <= phase[PHASE_ACC_W-1 -: SINE_IDX_W];
                        sine_frac <= phase[PHASE_ACC_W-SINE_IDX_W-1 -: SINE_FRAC_W];
                        phase     <= phase + phase_inc;
                        state     <= S_LFO_ADDR1;
                    end
                end

                S_LFO_ADDR1: begin
                    sine_addr <= sine_addr + 1'b1;   // wraps within the table
                    state     <= S_LFO_TAKE0;
                end

                S_LFO_TAKE0: begin
                    sine_s0 <= sine_q;
                    state   <= S_LFO_TAKE1;
                end

                S_LFO_TAKE1: begin
                    sine_s1 <= sine_q;
                    state   <= S_LFO_INTERP;
                end

                S_LFO_INTERP: begin
                    lfo   <= lfo_next;
                    state <= S_DELAY;
                end

                S_DELAY: begin
                    if (delay_unclamped < 40'(MIN_DELAY_Q))      delay_q <= 40'(MIN_DELAY_Q);
                    else if (delay_unclamped > 40'(MAX_DELAY_Q)) delay_q <= 40'(MAX_DELAY_Q);
                    else                                         delay_q <= delay_unclamped;
                    state <= S_SPLIT;
                end

                S_SPLIT: begin
                    // Whole samples pick the taps; the top FRAC_BITS of the
                    // remaining fraction weight the interpolation.
                    delay_int  <= ADDR_W'(delay_q >>> DELAY_Q);
                    delay_frac <= delay_q[DELAY_Q-1 -: FRAC_BITS];
                    state      <= S_ADDR_NEAR;
                end

                S_ADDR_NEAR: begin
                    rd_addr <= addr_near;
                    state   <= S_ADDR_FAR;
                end

                S_ADDR_FAR: begin
                    rd_addr <= addr_far;
                    state   <= S_TAKE_NEAR;
                end

                S_TAKE_NEAR: begin
                    s_near <= rd_data;      // buf[addr_near]
                    state  <= S_TAKE_FAR;
                end

                S_TAKE_FAR: begin
                    s_far <= rd_data;       // buf[addr_far]
                    state <= S_INTERP;
                end

                S_INTERP: begin
                    wet   <= 24'(interp >>> FRAC_BITS);
                    state <= S_MIX;
                end

                S_MIX: begin
                    sample_out       <= 24'(mixed >>> 16);
                    sample_out_valid <= 1'b1;
                    wr_addr          <= wr_addr + 1'b1;   // only now is wr_addr free
                    state            <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

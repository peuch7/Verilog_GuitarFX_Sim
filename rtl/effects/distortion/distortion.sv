`timescale 1ns / 1ps
//
// distortion.sv
//
// TODO (you): implement hard-clipping distortion with a tone control
//
// Right now this is a passthrough, so `wavsim run --effect distortion` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/distortion.json.
//
module distortion (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,

    input  logic [15:0]                  drive,  // Pre-clip gain. The clip threshold stays at full scale.
    input  logic [15:0]                  tone,  // 0 = dark (~800 Hz one-pole), 1 = open (~12 kHz).
    input  logic [15:0]                  level,  // Output attenuation, applied after clipping.

    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    // Audio full-scale limits for signed 24-bit
    localparam logic signed [39:0] MAX_SAMPLE = 40'sd8388607;
    localparam logic signed [39:0] MIN_SAMPLE = -40'sd8388608;

    // Tone filter state
    // Reference model:
    // y[n] = a*x[n] + (1-a)*y[n-1]
    logic signed [23:0] tone_state;

    // Tone coefficient lookup table
    // The python reference sweeps cutoff logarithmically:
    // cutoff = 800 * (12000/800)^tone
    // a = 1 - exp(-2*pi*cutoff/48000)
    // These values are a in Q0.16 at tone = 0/16 ... 16/16
    // Linear interpolation between entries gives a good
    // approximation without needing exp() hardware
    function automatic logic [15:0] tone_alpha_lut(
        input logic [4:0] index
    );
        begin
            case(index)
                5'd0:  tone_alpha_lut = 16'd6516;
                5'd1:  tone_alpha_lut = 16'd7645;
                5'd2:  tone_alpha_lut = 16'd8954;
                5'd3:  tone_alpha_lut = 16'd10466;
                5'd4:  tone_alpha_lut = 16'd12205;
                5'd5:  tone_alpha_lut = 16'd14194;
                5'd6:  tone_alpha_lut = 16'd16454;
                5'd7:  tone_alpha_lut = 16'd19003;
                5'd8:  tone_alpha_lut = 16'd21850;
                5'd9:  tone_alpha_lut = 16'd24999;
                5'd10: tone_alpha_lut = 16'd28435;
                5'd11: tone_alpha_lut = 16'd32131;
                5'd12: tone_alpha_lut = 16'd36035;
                5'd13: tone_alpha_lut = 16'd40073;
                5'd14: tone_alpha_lut = 16'd44147;
                5'd15: tone_alpha_lut = 16'd48138;
                5'd16: tone_alpha_lut = 16'd51912;
                default: tone_alpha_lut = 16'd51912;
            endcase
        end
    endfunction

    // Drive
    
    logic signed [39:0] driven_wide;
    always_comb begin
        // drive is an integer from 1 to 64
        driven_wide = $signed(sample_in) * $signed({1'b0, drive});
    end

    // Hard Clip

    logic signed [23:0] clipped;

    always_comb begin
        if (driven_wide > MAX_SAMPLE)
            clipped = 24'sd8388607;
        
        else if (driven_wide < MIN_SAMPLE)
            clipped = -24'sd8388608;

        else
            clipped = driven_wide[23:0];
    end

    // Tone Control

    logic [3:0] tone_index;
    logic [11:0] tone_fraction;

    logic [15:0] alpha_low;
    logic [15:0] alpha_high;
    logic [15:0] alpha_delta;

    logic [27:0] alpha_interp_product;
    logic [15:0] alpha;

    always_comb begin
        tone_index = tone[15:12];
        tone_fraction = tone[11:0];

        alpha_low = tone_alpha_lut({1'b0, tone_index});
        alpha_high = tone_alpha_lut({1'b0, tone_index} + 5'd1);

        alpha_delta = alpha_high - alpha_low;

        // Interpolate between LUT entries
        // tone_fraction is Q0.12, so shift by 12 afterward
        alpha_interp_product = alpha_delta * tone_fraction;

        alpha = alpha_low + alpha_interp_product[27:12];
    end

    // Calculate:
    // tone_next = tone_state + alpha * (clipped - tone_state)

    logic signed [24:0] tone_difference;
    logic signed [41:0] tone_product;
    logic signed [41:0] tone_delta;
    logic signed [41:0] tone_next_wide;
    logic signed [23:0] tone_next;

    always_comb begin

        tone_difference = 
            $signed({clipped[23], clipped}) -
            $signed({tone_state[23], tone_state});

        tone_product = tone_difference * $signed({1'b0, alpha});
        
        tone_delta = tone_product >>> 16;

        tone_next_wide = {{18{tone_state[23]}}, tone_state} + tone_delta;

        tone_next = tone_next_wide[23:0];
    end

    // Output Level

    logic signed [40:0] level_product;
    logic signed [40:0] leveled_wide;
    logic signed [23:0] leveled_sample;

    always_comb begin
        level_product = $signed(tone_next) * $signed({1'b0, level});

        leveled_wide = level_product >>> 16;

        leveled_sample = leveled_wide[23:0];
    end

    // Sequential state / valid handling
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            tone_state       <= 24'sd0;
            sample_out       <= 24'sd0;
            sample_out_valid <= 1'b0;
        end
        else begin

            // Default: valid is only high for one clock
            sample_out_valid <= 1'b0;

            if (sample_in_valid) begin
                tone_state <= tone_next;
                sample_out <= leveled_sample;
                sample_out_valid <= 1'b1;
            end
        end
    end

endmodule

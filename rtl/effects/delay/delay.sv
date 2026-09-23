`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 08/24/2026 10:59:48 AM
// Design Name: 
// Module Name: delay
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////


module delay (
    input clk,
    input signed [23:0] sample_in,
    input sample_in_valid,
    input [15:0] delay_samples, //max 48000
    input [15:0] feedback, //feedback being high means lots of repetitions. feedback 0 means 1 repetetion.
    input [15:0] mix, //mix being high means the delayed samples are loud compared to current. mix = 0 means only hear current
    
    output logic signed [23:0] sample_out,
    output logic sample_out_valid
    );
    
    localparam int MAX_DELAY_SAMPLES = 48000;
    localparam int ADDR_WIDTH = $clog2(MAX_DELAY_SAMPLES);
    
    logic [15:0] delay_samples_clipped;
    assign delay_samples_clipped = delay_samples > MAX_DELAY_SAMPLES ? MAX_DELAY_SAMPLES : delay_samples;
    logic [ADDR_WIDTH-1:0] max_addr;
    assign max_addr = delay_samples != 0 ? ADDR_WIDTH'(delay_samples_clipped - 1) : '0;
    
    (* ram_style = "block" *)
    logic signed [23:0] sample_buf [0:MAX_DELAY_SAMPLES - 1];    
    logic [ADDR_WIDTH - 1:0] cur_addr = 'd0;
    logic signed [23:0] old_sample = '0;
    logic signed [23:0] cur_sample = '0;
    logic signed [39:0] sample_out_unscaled;
    logic sample_out_unscaled_valid = '0;
    logic signed [39:0] to_be_stored_unscaled;
 
    initial begin
        for (int i = 0; i < MAX_DELAY_SAMPLES; i++) begin
            sample_buf[i] = 24'sd0;
        end
    end
    
    //we know this will fit in 40 bits (24 + 16), not 41
    //endpoint attenuation negligible (1/2^16)
    assign sample_out_unscaled = cur_sample * $signed({1'b0, (16'hFFFF - mix)}) +
                                 old_sample * $signed({1'b0, mix});
                                 
    assign to_be_stored_unscaled = sample_in  * $signed({1'b0, (16'hFFFF - feedback)}) + 
                                   old_sample * $signed({1'b0, feedback});
    
    always_ff @(posedge clk) begin
        sample_out_unscaled_valid <= 1'd0; //default
        
        sample_out <= sample_out_unscaled >>> 16;
        if (sample_in_valid) begin
            old_sample <= sample_buf[cur_addr];
            sample_out_unscaled_valid <= 1'd1;
            //store current sample in bram and also in a register for our combinational output
            sample_buf[cur_addr] <= to_be_stored_unscaled >>> 16;
            cur_sample <= sample_in;
            cur_addr <= (cur_addr == max_addr) ? 0 : cur_addr + 'd1;
        end
        
        sample_out_valid <= sample_out_unscaled_valid;
    end 
        
        
endmodule
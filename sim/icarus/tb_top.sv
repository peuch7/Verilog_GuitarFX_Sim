`timescale 1ns / 1ps
`include "effect_contract.svh"

// Generic Icarus testbench — the fallback backend, mirroring sim/verilator/sim_main.cpp
// cycle for cycle so `make crosscheck` can diff the two output streams byte for byte.
//
// The DUT is chosen at compile time:  iverilog -g2012 -DDUT_TOP=delay_top ...
//
// Streams are decimal text here rather than the canonical binary int32, because
// $fread fills a vector in big-endian order and byte-swapping in SV is not worth
// it for a fallback path. wavsim/backends.py converts in both directions, so the
// canonical format on disk is unchanged.
//
// Plusargs:
//   +in=PATH +out=PATH        sample streams (decimal, one per line)
//   +p0=N ... +p7=N           parameter slots
//   +cps=N                    clocks between sample_in_valid pulses
//   +flush=N                  sample periods to clock after the last input
//   +automation=PATH          optional "sample_index param_index value" lines
//   +stats=PATH               optional JSON run summary

`ifndef DUT_TOP
  `define DUT_TOP effect_top
`endif

module tb_top;

    localparam int RESET_CYCLES = 16;

    logic                            clk = 1'b0;
    logic                            rst_n = 1'b0;
    logic signed [`SAMPLE_WIDTH-1:0] sample_in = '0;
    logic                            sample_in_valid = 1'b0;
    logic [`PARAM_BUS_WIDTH-1:0]     params = '0;

    wire signed [`SAMPLE_WIDTH-1:0]  sample_out;
    wire                             sample_out_valid;

    `DUT_TOP dut (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .params           (params),
        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

    // 100 MHz, matching the nominal fabric clock. Only the ratio to the sample
    // strobe matters to the results.
    always #5 clk = ~clk;

    integer fin, fout, fstats, fauto;
    integer code;
    integer cps = 32;
    integer flush = 16;
    integer n_in = 0;
    integer n_out = 0;
    integer cycle = 0;
    integer first_in_cycle = -1;
    integer first_out_cycle = -1;
    integer sample_val;
    integer capture_enable = 0;
    integer feeding = 0;

    // Next pending automation event.
    integer ev_sample = -1;
    integer ev_index = 0;
    integer ev_value = 0;
    integer have_event = 0;

    string in_path;
    string out_path;
    string auto_path;
    string stats_path;

    // ---- cycle counter, for the latency report -------------------------
    always @(posedge clk) cycle <= cycle + 1;

    // ---- output capture -------------------------------------------------
    // Sampled on the falling edge so the values assigned at the rising edge have
    // settled. This reads exactly what Verilator reads after its post-edge eval();
    // sampling at posedge would read the pre-edge value and shift everything by
    // one sample.
    always @(negedge clk) begin
        if (capture_enable && sample_out_valid) begin
            // `cycle` has already counted the rising edge that produced this
            // sample, while first_in_cycle is recorded before its edge. Step back
            // one so the reported latency matches sim_main.cpp's numbering.
            if (first_out_cycle < 0) first_out_cycle = cycle - 1;
            $fdisplay(fout, "%0d", $signed(sample_out));
            n_out = n_out + 1;
        end
    end

    // ---- parameter slots -------------------------------------------------
    task automatic load_params;
        integer v;
        begin
            if ($value$plusargs("p0=%d", v)) params[`PARAM_WIDTH*0 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p1=%d", v)) params[`PARAM_WIDTH*1 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p2=%d", v)) params[`PARAM_WIDTH*2 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p3=%d", v)) params[`PARAM_WIDTH*3 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p4=%d", v)) params[`PARAM_WIDTH*4 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p5=%d", v)) params[`PARAM_WIDTH*5 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p6=%d", v)) params[`PARAM_WIDTH*6 +: `PARAM_WIDTH] = v[15:0];
            if ($value$plusargs("p7=%d", v)) params[`PARAM_WIDTH*7 +: `PARAM_WIDTH] = v[15:0];
        end
    endtask

    task automatic set_param(input integer index, input integer value);
        begin
            case (index)
                0: params[`PARAM_WIDTH*0 +: `PARAM_WIDTH] = value[15:0];
                1: params[`PARAM_WIDTH*1 +: `PARAM_WIDTH] = value[15:0];
                2: params[`PARAM_WIDTH*2 +: `PARAM_WIDTH] = value[15:0];
                3: params[`PARAM_WIDTH*3 +: `PARAM_WIDTH] = value[15:0];
                4: params[`PARAM_WIDTH*4 +: `PARAM_WIDTH] = value[15:0];
                5: params[`PARAM_WIDTH*5 +: `PARAM_WIDTH] = value[15:0];
                6: params[`PARAM_WIDTH*6 +: `PARAM_WIDTH] = value[15:0];
                7: params[`PARAM_WIDTH*7 +: `PARAM_WIDTH] = value[15:0];
                default: $display("tb_top: ignoring automation for param %0d", index);
            endcase
        end
    endtask

    task automatic fetch_event;
        begin
            have_event = 0;
            if (fauto != 0) begin
                code = $fscanf(fauto, "%d %d %d", ev_sample, ev_index, ev_value);
                if (code == 3) have_event = 1;
            end
        end
    endtask

    task automatic apply_due_events;
        begin
            while (have_event && ev_sample <= n_in) begin
                set_param(ev_index, ev_value);
                fetch_event;
            end
        end
    endtask

    // ---- main sequence ---------------------------------------------------
    initial begin
        if (!$value$plusargs("in=%s", in_path)) begin
            $display("tb_top: error, +in=PATH is required");
            $finish;
        end
        if (!$value$plusargs("out=%s", out_path)) begin
            $display("tb_top: error, +out=PATH is required");
            $finish;
        end
        // Assigned rather than wrapped in void'(): Icarus 11, which is what
        // Debian ships and therefore what the container has, rejects the cast.
        code = $value$plusargs("cps=%d", cps);
        code = $value$plusargs("flush=%d", flush);
        if (cps < 1) cps = 1;

        fin = $fopen(in_path, "r");
        if (fin == 0) begin
            $display("tb_top: error, cannot open %0s", in_path);
            $finish;
        end
        fout = $fopen(out_path, "w");
        if (fout == 0) begin
            $display("tb_top: error, cannot create %0s", out_path);
            $finish;
        end

        fauto = 0;
        if ($value$plusargs("automation=%s", auto_path)) begin
            fauto = $fopen(auto_path, "r");
            if (fauto == 0) $display("tb_top: warning, cannot open %0s", auto_path);
        end

        load_params;
        fetch_event;

        // Reset, then exactly one idle cycle with reset released before the
        // first sample. sim_main.cpp does the same.
        repeat (RESET_CYCLES) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        capture_enable = 1;
        @(negedge clk);

        // Icarus does not implement `break`, so the loop is flag driven.
        feeding = 1;
        while (feeding) begin
            apply_due_events;

            code = $fscanf(fin, "%d", sample_val);
            if (code != 1) begin
                feeding = 0;
            end else begin
                sample_in = sample_val[`SAMPLE_WIDTH-1:0];
                sample_in_valid = 1'b1;
                if (first_in_cycle < 0) first_in_cycle = cycle;
                n_in = n_in + 1;

                @(negedge clk);          // the rising edge in between consumes it
                sample_in_valid = 1'b0;
                sample_in = '0;
                repeat (cps - 1) @(negedge clk);
            end
        end

        repeat (flush * cps) @(negedge clk);

        $fclose(fin);
        $fclose(fout);
        if (fauto != 0) $fclose(fauto);

        $display("icarus: %0d in -> %0d out, latency %0d cycles",
                 n_in, n_out, (first_out_cycle >= 0 && first_in_cycle >= 0)
                              ? (first_out_cycle - first_in_cycle) : -1);

        if ($value$plusargs("stats=%s", stats_path)) begin
            fstats = $fopen(stats_path, "w");
            if (fstats != 0) begin
                $fdisplay(fstats, "{");
                $fdisplay(fstats, "  \"backend\": \"icarus\",");
                $fdisplay(fstats, "  \"samples_in\": %0d,", n_in);
                $fdisplay(fstats, "  \"samples_out\": %0d,", n_out);
                $fdisplay(fstats, "  \"cycles\": %0d,", cycle);
                $fdisplay(fstats, "  \"cycles_per_sample\": %0d,", cps);
                $fdisplay(fstats, "  \"latency_cycles\": %0d",
                          (first_out_cycle >= 0 && first_in_cycle >= 0)
                          ? (first_out_cycle - first_in_cycle) : -1);
                $fdisplay(fstats, "}");
                $fclose(fstats);
            end
        end

        $finish;
    end

endmodule

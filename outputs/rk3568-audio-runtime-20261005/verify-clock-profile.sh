#!/bin/sh
# Exact tested Image, TRCM=1, 48kHz stereo: RX config persists while clocks close.
set -efu
test "$#" = 2
before=$1
after=$2
test -f "$before"
test -f "$after"
before_names=
after_names=
before_count=0
after_count=0
while read -r name enable prepare protect rate accuracy phase duty extra; do
    test -n "$name"
    test -z "$extra"
    before_names="$before_names $name"
    before_count=$((before_count + 1))
done < "$before"
while read -r name enable prepare protect rate accuracy phase duty extra; do
    test -n "$name"
    test -z "$extra"
    after_names="$after_names $name"
    after_count=$((after_count + 1))
done < "$after"
test "$before_count:$after_count" = 16:16
test "$before_names" = ' i2s1_mclkout_rx clk_i2s1_8ch_rx_src clk_i2s1_8ch_rx mclk_i2s1_8ch_rx clk_i2s1_8ch_rx_frac clk_i2s1_8ch_tx_src clk_i2s1_8ch_tx_frac clk_i2s1_8ch_tx mclk_i2s1_8ch_tx i2s1_mclkout_tx i2s1_mclk_tx_ioe i2s1_mclkout hclk_i2s1_8ch i2s1_mclkin_tx i2s1_mclkin_rx i2s1_mclk_rx_ioe'
test "$after_names" = ' i2s1_mclkout_rx clk_i2s1_8ch_rx_src clk_i2s1_8ch_rx_frac clk_i2s1_8ch_rx mclk_i2s1_8ch_rx clk_i2s1_8ch_tx_src clk_i2s1_8ch_tx_frac clk_i2s1_8ch_tx mclk_i2s1_8ch_tx i2s1_mclkout_tx i2s1_mclk_tx_ioe i2s1_mclkout hclk_i2s1_8ch i2s1_mclkin_tx i2s1_mclkin_rx i2s1_mclk_rx_ioe'
for name in $before_names; do
    original=$(grep -E "^[[:space:]]*$name[[:space:]]" "$before")
    current=$(grep -E "^[[:space:]]*$name[[:space:]]" "$after")
    set -- $original
    test "$#" = 8
    original_profile="$1 $2 $3 $4 $5 $6 $7 $8"
    case "$name" in
        clk_i2s1_8ch_rx|mclk_i2s1_8ch_rx|clk_i2s1_8ch_rx_frac)
            test "$original_profile" = "$name 0 0 0 1188000000 0 0 50000"
            set -- $current
            test "$#" = 8
            test "$1 $2 $3 $4 $5 $6 $7 $8" = "$name 0 0 0 12288000 0 0 50000"
            ;;
        *)
            set -- $current
            test "$#" = 8
            test "$original_profile" = "$1 $2 $3 $4 $5 $6 $7 $8"
            # Every unaffected clock retains its exact parent depth.
            test "$original" = "$current"
            ;;
    esac
done
# Only clk_rx changes parent rx_src -> rx_frac; leaf and frac parents persist.
grep -E '^             clk_i2s1_8ch_rx ' "$before" > /dev/null
grep -E '^                mclk_i2s1_8ch_rx ' "$before" > /dev/null
grep -E '^             clk_i2s1_8ch_rx_frac ' "$before" > /dev/null
grep -E '^             clk_i2s1_8ch_rx_frac ' "$after" > /dev/null
grep -E '^                clk_i2s1_8ch_rx ' "$after" > /dev/null
grep -E '^                   mclk_i2s1_8ch_rx ' "$after" > /dev/null
echo PCM_CLOCK_COUNTS_RESTORED_INACTIVE_RX_CONFIGURATION_RETAINED

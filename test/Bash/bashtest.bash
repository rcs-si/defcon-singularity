#!/bin/bash
set -euo pipefail

echo "Shell test start"

seq 1 10000 > nums.txt
awk '{sum += $1} END {print "Sum:", sum}' nums.txt > sum.txt
sort -r nums.txt | head -5 > top5.txt

paste -d, <(head -3 nums.txt) <(head -3 top5.txt) > paired.csv

echo "Top 5 values:"
cat top5.txt

echo "Shell pipeline OK"
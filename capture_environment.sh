#!/bin/bash
# Capture environment variables in a format suitable for Singularity containers
# This script creates an env -0 output file needed by def_generator.py

set -e

OUTPUT_FILE="${1:-.env_dump}"

if [ -z "$1" ]; then
    echo "Usage: $0 <output_file>"
    echo ""
    echo "This script captures the current environment variables in null-byte"
    echo "separated format, suitable for use with def_generator.py"
    echo ""
    echo "Example:"
    echo "  $0 /tmp/myenv.out"
    echo ""
fi

echo "Capturing environment to $OUTPUT_FILE..."

# Use env -0 to output variables in null-separated format
env -0 > "$OUTPUT_FILE"

echo "Done! Environment saved to: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "1. Run your script under strace:"
echo "   strace -f -e trace=file -s 0 -o trace.out <your_command>"
echo ""
echo "2. Generate the Singularity definition:"
echo "   python def_generator.py trace.out \\"
echo "       --env $OUTPUT_FILE \\"
echo "       --run-command '<your_command>' \\"
echo "       --output container.def"

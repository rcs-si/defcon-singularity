#!/bin/bash
# Run a command under strace with SGE job scheduler support
# Useful for capturing dependencies of long-running jobs

set -e

COMMAND=""
OUTPUT_TRACE="trace.out"
OUTPUT_ENV="env.out"
USE_QSUB=false
USE_SLURM=false
HELP=false

print_help() {
    echo "Usage: $0 [OPTIONS] -- <command>"
    echo ""
    echo "Run a command under strace and capture environment for containerization"
    echo ""
    echo "Options:"
    echo "  -o, --output TRACEFILE    Output trace file (default: trace.out)"
    echo "  -e, --env ENVFILE         Output environment file (default: env.out)"
    echo "  --qsub                    Submit as SGE job (qsub)"
    echo "  --slurm                   Submit as SLURM job (sbatch)"
    echo "  -h, --help                Show this help message"
    echo ""
    echo "Examples:"
    echo ""
    echo "  # Direct execution"
    echo "  $0 -- python test.py"
    echo ""
    echo "  # With custom output files"
    echo "  $0 -o my_trace.out -e my_env.out -- python test.py"
    echo ""
    echo "  # With SGE job scheduler"
    echo "  $0 --qsub -- python test.py"
    echo ""
    echo "  # With SLURM job scheduler"
    echo "  $0 --slurm -- python test.py"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -o|--output)
            OUTPUT_TRACE="$2"
            shift 2
            ;;
        -e|--env)
            OUTPUT_ENV="$2"
            shift 2
            ;;
        --qsub)
            USE_QSUB=true
            shift
            ;;
        --slurm)
            USE_SLURM=true
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        --)
            shift
            COMMAND="$@"
            break
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
    esac
done

if [ -z "$COMMAND" ]; then
    echo "Error: No command specified"
    print_help
    exit 1
fi

# Create a wrapper script for strace
WRAPPER_SCRIPT=$(mktemp /tmp/strace_wrapper_XXXXXX.sh)
trap "rm -f $WRAPPER_SCRIPT" EXIT

cat > "$WRAPPER_SCRIPT" << 'WRAPPER_EOF'
#!/bin/bash
set -e

OUTPUT_TRACE="$1"
OUTPUT_ENV="$2"
shift 2
COMMAND="$@"

# Capture environment
echo "Capturing environment..."
env -0 > "$OUTPUT_ENV"

# Run command under strace
echo "Running command under strace: $COMMAND"
strace -f -e trace=file -s 0 -o "$OUTPUT_TRACE" $COMMAND

echo ""
echo "Done!"
echo "Trace file: $OUTPUT_TRACE"
echo "Environment file: $OUTPUT_ENV"
WRAPPER_EOF

chmod +x "$WRAPPER_SCRIPT"

if [ "$USE_QSUB" = true ]; then
    echo "Submitting to SGE (qsub)..."
    cat > /tmp/qsub_job_$$.sh << QSUB_EOF
#!/bin/bash
#$ -S /bin/bash
#$ -cwd
"$WRAPPER_SCRIPT" "$OUTPUT_TRACE" "$OUTPUT_ENV" $COMMAND
QSUB_EOF
    chmod +x /tmp/qsub_job_$$.sh
    qsub /tmp/qsub_job_$$.sh
    echo "Job submitted. Check job status with 'qstat'"
elif [ "$USE_SLURM" = true ]; then
    echo "Submitting to SLURM (sbatch)..."
    cat > /tmp/slurm_job_$$.sh << SLURM_EOF
#!/bin/bash
"$WRAPPER_SCRIPT" "$OUTPUT_TRACE" "$OUTPUT_ENV" $COMMAND
SLURM_EOF
    chmod +x /tmp/slurm_job_$$.sh
    sbatch /tmp/slurm_job_$$.sh
    echo "Job submitted. Check job status with 'squeue'"
else
    # Direct execution
    "$WRAPPER_SCRIPT" "$OUTPUT_TRACE" "$OUTPUT_ENV" $COMMAND
fi

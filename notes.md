===============================
AUTO-CONTAINER BUILD WORKFLOW
===============================

# 0. Prepare a test Python script
echo 'import pandas as pd
print(pd.DataFrame({"a":[1,2,3]}))' > test.py

# 1. Run your script under strace to collect dependencies
strace -f -e trace=file -s 0 -o trace.out python test.py

# 2. Parse the trace into a filtered file list
# (Assumes strace_parser.py is in current directory)
python strace_parser.py trace.out > parsed_files.txt

# 3. Generate a Singularity definition file (auto.def)
python def_generator.py trace.out \
    --run-command "python /projectnb/rcs-intern/reetom/sif/test.py" \
    --output auto.def

# 4. Build the container image using remote builder
# NOTE: kaboom (make an account or something? --remote build)
singularity build --remote auto.sif auto.def

# 5. Run the container
# Method A: direct exec
singularity exec auto.sif python /projectnb/rcs-intern/reetom/sif/test.py

# Method B: use %runscript (runs default command)
singularity run auto.sif


# 6. Inspect the container
singularity inspect auto.sif
singularity shell auto.sif

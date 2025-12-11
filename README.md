Basic idea: make a tool that runs a program or script. It will analyze the files & directories used using the `strace` tool. 
The output will be a Singularity .def file that can build a container that can run the program or script.

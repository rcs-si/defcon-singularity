/* Compile: mpicc -O2 mpi_sum.c -o mpi_sum. Run inside an allocation. */
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);
    int rank, ranks;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &ranks);
    long n = argc > 1 ? atol(argv[1]) : 10000;
    if (n < 1 || n > 100000000) { MPI_Abort(MPI_COMM_WORLD, 2); }
    double scale = argc > 2 ? atof(argv[2]) : 1.0;
    double local = 0, total = 0;
    for (long i = rank + 1; i <= n; i += ranks) local += scale * i;
    MPI_Reduce(&local, &total, 1, MPI_DOUBLE, MPI_SUM, 0, MPI_COMM_WORLD);
    if (rank == 0) printf("{\"result\": %.17g, \"ranks\": %d}\n", total, ranks);
    MPI_Finalize();
    return 0;
}

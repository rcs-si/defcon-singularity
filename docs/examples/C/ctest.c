#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int main() {
    int n = 1000;
    double sum = 0.0;

    for (int i = 0; i < n; i++) {
        double x = (double)i / n;
        sum += sin(x) * cos(x) + sqrt(x + 1.0);
    }

    printf("Math test OK: sum = %.6f\n", sum);

    FILE *fp = fopen("c_output.txt", "w");
    if (!fp) {
        perror("fopen");
        return 1;
    }

    fprintf(fp, "Computed sum: %.6f\n", sum);
    fclose(fp);

    fp = fopen("c_output.txt", "r");
    if (!fp) {
        perror("fopen read");
        return 1;
    }

    char buffer[256];
    if (fgets(buffer, sizeof(buffer), fp) != NULL) {
        printf("File I/O OK: %s", buffer);
    }
    fclose(fp);

    printf("All C tests passed.\n");
    return 0;
}
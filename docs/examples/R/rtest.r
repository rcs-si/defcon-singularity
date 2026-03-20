set.seed(123)

library(data.table)

# Matrix multiply / solve (BLAS/LAPACK)
A <- matrix(runif(100 * 100), nrow = 100)
B <- matrix(runif(100 * 100), nrow = 100)
C <- A %*% B
cat(sprintf("Matrix multiply OK: dim=%d x %d, mean=%.4f\n", nrow(C), ncol(C), mean(C)))

M <- matrix(runif(200 * 200), nrow = 200)
M <- M %*% t(M) + diag(200)
b <- runif(200)
x <- solve(M, b)
resid <- sqrt(sum((M %*% x - b)^2))
cat(sprintf("Linear solve OK: residual=%.2e\n", resid))

# data.table aggregation
dt <- data.table(
  group = rep(c("a", "b", "c"), each = 1000),
  value = rnorm(3000)
)
summary_dt <- dt[, .(
  mean = mean(value),
  sd = sd(value),
  count = .N
), by = group]
print(summary_dt)

# File I/O
fwrite(summary_dt, "r_summary.csv")
dt2 <- fread("r_summary.csv")
cat(sprintf("CSV roundtrip OK: %d rows\n", nrow(dt2)))

cat("All R tests passed.\n")
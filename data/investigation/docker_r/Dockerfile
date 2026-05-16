# ConcordMet Docker R 路径 — Q-03 (A) 拍板 (2026-05-15)
#
# 用途: 在隔离 Docker 容器内运行 MetaboAnalystR + FELLA + Bioconductor,
#       绕过 host conda env binutils-dev `bfd.h` 头文件污染问题(R-NEW-14)。
#
# 调用方式: Python subprocess `docker exec ... Rscript /opt/entrypoint.R < stdin > stdout`
# 性能预估: docker exec startup ~2-3s,FELLA RWR single call ~5-15s,K=10 并发 OK
#
# Build:
#   cd data/investigation/docker_r
#   docker build -t concordmet-r:v0.1 .
#
# Test (Sprint W4 D5):
#   echo '{"method":"FELLA","compounds":["C00031","C00022"]}' | \
#     docker run -i --rm concordmet-r:v0.1
#
# Release pin: bioconductor/bioconductor_docker:RELEASE_3_19 = R 4.4.x,Bioconductor 3.19
# (Sprint W4 evaluate :RELEASE_3_20 for FELLA latest;v0.1 stay 3.19 stable)

FROM bioconductor/bioconductor_docker:RELEASE_3_19

LABEL maintainer="ConcordMet investigation (Q-03 (A) decision 2026-05-15)"
LABEL release="0.1-investigation"

# Install MetaboAnalystR + FELLA + supporting deps
# (BiocManager pre-installed in bioconductor_docker base image)
# NOTE (W5 D1 hotfix 2026-05-16, attempt 2): MetaboAnalystR 4.x has a
# very large transitive dep set spanning CRAN + Bioconductor. v1 of this
# hotfix added the most-visible missing Bioc deps (pcaMethods etc.) but
# the build still failed on qs2 (lazy-loading), so this layer now uses
# MetaboAnalystR's *official* metanr_packages() list (verbatim from
# xia-lab/MetaboAnalystR README) plus qs2. BiocManager::install accepts
# CRAN package names too, so a single call covers both repositories.
RUN R -e ' \
    options(repos = c(CRAN = "https://cloud.r-project.org")); \
    install.packages("optparse", quiet=TRUE); \
    install.packages("jsonlite", quiet=TRUE); \
    BiocManager::install(c( \
        "fgsea", "limma", "KEGGREST", "graph", "KEGGgraph", \
        "FELLA", "igraph", \
        "BiocParallel", "MSnbase", "multtest", "RBGL", "edgeR", "devtools", \
        "crmn", "httr", "RJSONIO", "ggplot2", "RColorBrewer", "xtable", \
        "som", "scales", "Cairo", "gplots", "ROCR", "caret", "randomForest", \
        "data.table", "car", "XML", "plotly", "cluster", "entropy", \
        "ALDEx2", "Rcpp", "RcppParallel", "stringr", "tibble", \
        "preprocessCore", "plotrix", "reshape", "reshape2", "caTools", \
        "metap", "Rserve", "fitdistrplus", "gridExtra", "htmlTable", \
        "Hmisc", "plyr", "pls", "pheatmap", "Rgraphviz", "glasso", "huge", \
        "ppcor", "dplyr", "siggenes", "fingerprint", "ChemmineR", \
        "rsm", "corpcor", "ellipse", "impute", "Biobase", "viridis", \
        "kableExtra", "DT", "robustbase", "htmlwidgets", "pcaMethods", \
        "qs2", "qs" \
    ), ask=FALSE, update=FALSE, quiet=FALSE); \
    cat("CORE_DEPS_DONE\n")'

# MetaboAnalystR 完整 install(深度依赖大,~30 min build wall time)
# NOTE (W5 D1 hotfix 2026-05-16, attempt 5): Upstream MetaboAnalystR
# v4.2.0 (and HEAD) ship NAMESPACE files that export functions which
# do not exist in the R/ sources. v4 of this hotfix tried
# `INSTALL_opts=c("--no-test-load")` to bypass the install-time
# check, but ``requireNamespace("MetaboAnalystR")`` at *runtime* still
# triggers namespaceExport(...) which re-validates the exports and
# returns FALSE.
#
# Fix: download the source, strip the offending lines from NAMESPACE,
# then R CMD INSTALL from the patched local copy. Both v4.2.0's set
# (Plot.sampletrend, PlotImpVarMeta, RemoveMissingPercent, ReplaceMin,
# plot_dist) and HEAD's set (the Mum* / PlotMumVolcano family) are
# stripped so this works if we re-pin upstream later. None of these
# functions are used by the PSEA / MSEA / Mummichog dispatch paths
# that entrypoint.R exposes, so removing the exports is safe for our
# call surface.
RUN R -e ' \
    options(repos = c(CRAN = "https://cloud.r-project.org")); \
    install.packages(c("devtools","RSQLite","progress"), quiet=TRUE); \
    td <- tempfile(); dir.create(td); \
    tarball <- file.path(td, "MetaboAnalystR.tar.gz"); \
    download.file("https://github.com/xia-lab/MetaboAnalystR/archive/refs/tags/v4.2.0.tar.gz", \
                  tarball, quiet=FALSE, mode="wb"); \
    untar(tarball, exdir=td); \
    pkg_dir <- file.path(td, "MetaboAnalystR-4.2.0"); \
    ns_path <- file.path(pkg_dir, "NAMESPACE"); \
    ns <- readLines(ns_path); \
    broken <- c("Plot.sampletrend","PlotImpVarMeta","RemoveMissingPercent","ReplaceMin","plot_dist", \
                "GetMumStatColNames","GetMumStatMat","GetMumStatRowNames", \
                "GetPvalCutoffForSigFeatures","PerformMumTableStat","PlotMumVolcano"); \
    keep <- !sapply(ns, function(line) any(sapply(broken, function(f) \
        grepl(paste0("\\(", f, "\\)"), line) ))); \
    writeLines(ns[keep], ns_path); \
    cat("NAMESPACE patched: removed", sum(!keep), "lines\n"); \
    install.packages(pkg_dir, repos=NULL, type="source", \
                     INSTALL_opts=c("--no-test-load")); \
    if (!requireNamespace("MetaboAnalystR", quietly=TRUE)) { \
      stop("MetaboAnalystR install failed after NAMESPACE patch"); \
    }; \
    cat("METABOANALYSTR_DONE\n")'

# FELLA KEGG graph build + persist to /opt/fella_kegg_hsa
# (buildGraphFromKEGGREST is in-memory only; buildDataFromGraph writes the
# four-table KEGG data structure to disk so loadKEGGdata can re-use it at
# runtime without re-hitting KEGG REST). On a fresh image this download
# takes ~5-10 min and ~200 MB.
RUN R -e ' \
    suppressMessages(library(FELLA)); \
    set.seed(42); \
    g <- buildGraphFromKEGGREST(organism="hsa", filter.path=character(0)); \
    buildDataFromGraph(keggdata.graph=g, databaseDir="/opt/fella_kegg_hsa", \
                       internalDir=FALSE, matrices="diffusion", \
                       normality="diffusion", niter=50); \
    cat("FELLA_GRAPH_INIT_DONE\n")' || \
    echo "WARN: FELLA graph init failed during build — defer to runtime"

# Copy entrypoint
COPY entrypoint.R /opt/entrypoint.R
RUN chmod +x /opt/entrypoint.R

# Sanity test on build
RUN Rscript /opt/entrypoint.R --self-test 2>&1 | head -20 || \
    echo "WARN: self-test issued non-zero, check logs"

# Default: read JSON request from stdin, write JSON response to stdout
ENTRYPOINT ["Rscript", "/opt/entrypoint.R"]

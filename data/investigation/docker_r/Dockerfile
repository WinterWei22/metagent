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
# NOTE (W5 D1 hotfix 2026-05-16, attempt 3): HEAD of xia-lab/MetaboAnalystR
# is currently 4.3.0 with a broken NAMESPACE file — exports undefined
# functions (GetMumStatColNames, GetMumStatMat, GetMumStatRowNames,
# GetPvalCutoffForSigFeatures, PerformMumTableStat, PlotMumVolcano) and
# fails with "package or namespace load failed … undefined exports".
# This is an upstream bug; pinning to ref="v4.2.0" (89dd939, the most
# recent stable release tag) avoids it.
# Fail-loud guard kept: if install fails despite the pin, the layer
# fails the build instead of silently leaving the image MetaboAnalystR-less.
RUN R -e ' \
    install.packages("devtools", quiet=TRUE); \
    devtools::install_github("xia-lab/MetaboAnalystR", ref="v4.2.0", \
                             build_vignettes=FALSE, \
                             upgrade="never", quiet=FALSE); \
    if (!requireNamespace("MetaboAnalystR", quietly=TRUE)) { \
      stop("MetaboAnalystR install failed — check upstream deps"); \
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

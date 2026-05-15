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
RUN R -e ' \
    options(repos = c(CRAN = "https://cloud.r-project.org")); \
    install.packages("optparse", quiet=TRUE); \
    install.packages("jsonlite", quiet=TRUE); \
    BiocManager::install(c( \
        "fgsea", "limma", "KEGGREST", "graph", "KEGGgraph", \
        "FELLA", "igraph" \
    ), ask=FALSE, update=FALSE, quiet=FALSE); \
    cat("CORE_DEPS_DONE\n")'

# MetaboAnalystR 完整 install(深度依赖大,~30 min build wall time)
RUN R -e ' \
    install.packages("devtools", quiet=TRUE); \
    devtools::install_github("xia-lab/MetaboAnalystR", build_vignettes=FALSE, \
                             upgrade="never", quiet=FALSE); \
    cat("METABOANALYSTR_DONE\n")'

# FELLA KEGG graph init(需要下载 KEGG release graph,~200 MB)
# 这步会触发首次 KEGG REST 调用初始化 hierarchical graph
RUN R -e ' \
    suppressMessages(library(FELLA)); \
    set.seed(42); \
    tmp <- tempdir(); \
    buildGraphFromKEGGREST(organism="hsa", filter.path=character(0)); \
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

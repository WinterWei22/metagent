#!/usr/bin/env Rscript
# ConcordMet Docker R entrypoint — Q-03 (A) Sprint W4 background hedge
#
# Input:  stdin = JSON request {"method": "fella_rwr|metaboanalystr_psea", "params": {...}}
# Output: stdout = JSON response with EnrichmentResult v0.3 shape
#
# Usage:
#   echo '{"method": "self_test"}' | Rscript /opt/entrypoint.R
#   docker run -i --rm concordmet-r:v0.1 < request.json > response.json

suppressMessages({
  library(jsonlite)
  library(optparse)
})

# ---------------------------------------------------------------------------
# Parse command-line flags
# ---------------------------------------------------------------------------
option_list <- list(
  make_option("--self-test", action="store_true", default=FALSE,
              help="Run self-test (verify all packages import) and exit"),
  make_option("--verbose",   action="store_true", default=FALSE,
              help="Verbose stderr logging"),
  make_option("--method",    type="character",   default=NULL,
              help="Override stdin method dispatch (debugging)")
)
parser <- OptionParser(option_list=option_list)
args <- parse_args(parser)

log_msg <- function(...) {
  if (args$verbose) cat("[entrypoint]", ..., "\n", file=stderr())
}

# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if (args$`self-test`) {
  log_msg("Running self-test")
  pkgs <- c("FELLA", "MetaboAnalystR", "fgsea", "KEGGgraph", "igraph", "jsonlite")
  results <- list()
  for (p in pkgs) {
    ok <- requireNamespace(p, quietly=TRUE)
    results[[p]] <- ok
    cat(sprintf("  %-18s %s\n", p, if (ok) "OK" else "MISSING"))
  }
  all_ok <- all(unlist(results))
  cat(toJSON(list(self_test="done", packages=results, all_ok=all_ok),
             auto_unbox=TRUE), "\n")
  quit(status=if (all_ok) 0 else 1)
}

# ---------------------------------------------------------------------------
# Read JSON request from stdin
# ---------------------------------------------------------------------------
request_raw <- readLines(con="stdin", warn=FALSE)
if (length(request_raw) == 0) {
  cat(toJSON(list(error="empty stdin request"), auto_unbox=TRUE), "\n")
  quit(status=2)
}
request <- tryCatch(
  fromJSON(paste(request_raw, collapse="\n")),
  error=function(e) {
    cat(toJSON(list(error=paste("JSON parse:", conditionMessage(e))),
               auto_unbox=TRUE), "\n")
    quit(status=2)
  }
)

method <- if (!is.null(args$method)) args$method else request$method
if (is.null(method)) {
  cat(toJSON(list(error="missing 'method' in request"), auto_unbox=TRUE), "\n")
  quit(status=2)
}

# ---------------------------------------------------------------------------
# Method dispatch (W4-W5 实施期填实)
# ---------------------------------------------------------------------------
dispatch <- function(method, request) {
  switch(
    method,
    "fella_rwr"          = run_fella_rwr(request),
    "fella_diffusion"    = run_fella_diffusion(request),
    "metaboanalystr_psea"= run_metaboanalystr_psea(request),
    "metaboanalystr_msea"= run_metaboanalystr_msea(request),
    list(error=paste("unknown method:", method))
  )
}

# ---------------------------------------------------------------------------
# FELLA RWR (W5 D2 实施)
# ---------------------------------------------------------------------------
run_fella_rwr <- function(request) {
  # TODO Sprint W5 D2:
  #   1. params$compounds: list of KEGG cpd IDs or ChEBI IDs(via §5 crosswalk to KEGG)
  #   2. params$organism: "hsa" default
  #   3. Load FELLA hierarchical graph(image cached during docker build)
  #   4. enrich(...) RWR with restart prob 0.85
  #   5. Get pathway-level nodes only
  #   6. Return EnrichmentResult v0.3 JSON shape (per data/investigation/scripts/enrichment_result_schema_draft.py)
  list(
    method="fella_rwr",
    status="NOT_IMPLEMENTED",
    note="W5 D2 fill-in;params received=names(request$params)",
    request_keys=names(request)
  )
}

run_fella_diffusion <- function(request) {
  list(method="fella_diffusion", status="NOT_IMPLEMENTED", note="W5 D2")
}

# ---------------------------------------------------------------------------
# MetaboAnalystR (W5 D1 实施)
# ---------------------------------------------------------------------------
run_metaboanalystr_psea <- function(request) {
  # TODO Sprint W5 D1:
  #   1. params$compounds: list of HMDB / KEGG IDs
  #   2. MetaboAnalystR PerformPSEA
  #   3. Return EnrichmentResult v0.3 JSON shape
  list(method="metaboanalystr_psea", status="NOT_IMPLEMENTED", note="W5 D1")
}

run_metaboanalystr_msea <- function(request) {
  list(method="metaboanalystr_msea", status="NOT_IMPLEMENTED", note="W5 D1")
}

# ---------------------------------------------------------------------------
# Execute + emit JSON response
# ---------------------------------------------------------------------------
response <- tryCatch(
  dispatch(method, request),
  error=function(e) list(error=paste("exception:", conditionMessage(e)))
)
# Add wall time for traceability
if (is.list(response) && is.null(response$error)) {
  response$wall_time_sec <- as.numeric(proc.time()["elapsed"])
}
cat(toJSON(response, auto_unbox=TRUE, na="null"), "\n")
quit(status=if (!is.null(response$error)) 1 else 0)

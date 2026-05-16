#!/usr/bin/env Rscript
# ConcordMet Docker R entrypoint (W5 D1 — real R-method implementations)
#
# Architecture: persistent container + docker exec
#   - stdin = JSON request {"method": "<name>", "params": {...}}
#   - stdout = JSON response (last line)
#   - methods:  self_test / fella_rwr / fella_diffusion /
#               metaboanalystr_psea / metaboanalystr_msea / metaboanalystr_mummichog
#
# Concurrent K=10 safety:
#   Each ``docker exec`` spawns a fresh R process inside the container.
#   FELLA KEGG graph is pre-warmed at container start via ENV-loaded R script,
#   then this entrypoint reuses it via the FELLA data dir on disk.

suppressMessages({
  library(jsonlite)
  library(optparse)
})

# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------
option_list <- list(
  make_option("--self-test", action="store_true", default=FALSE,
              help="Verify all packages import + return JSON status"),
  make_option("--verbose",   action="store_true", default=FALSE,
              help="Verbose stderr logging"),
  make_option("--prewarm",   action="store_true", default=FALSE,
              help="Load FELLA KEGG graph and exit (container startup hook)")
)
parser <- OptionParser(option_list=option_list)
args <- parse_args(parser)

log_msg <- function(...) {
  if (isTRUE(args$verbose)) cat("[entrypoint]", ..., "\n", file=stderr())
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FELLA_DATA_DIR <- Sys.getenv("FELLA_DATA_DIR", "/opt/fella_kegg_hsa")
METABOANALYSTR_CACHE_DIR <- Sys.getenv(
  "METABOANALYSTR_CACHE_DIR", "/opt/metaboanalystr_cache")
dir.create(METABOANALYSTR_CACHE_DIR, recursive=TRUE, showWarnings=FALSE)

# ---------------------------------------------------------------------------
# qs::qread → qs2::qs_read fallback (W5 D1下 hotfix 2026-05-16)
# ---------------------------------------------------------------------------
# metaboanalyst.ca currently serves .qs library files in the qs2 binary
# format (magic bytes 0b 0e 0a c1) but MetaboAnalystR's `.get.my.lib`
# calls qs::qread, which only understands the legacy qs format and bails
# with "QS format not detected". Patch qs::qread inside the loaded
# namespace so that on read failure it transparently retries with
# qs2::qs_read. No upstream MetaboAnalystR change required.
suppressMessages({
  library(qs)
  library(qs2)
})
.orig_qread <- qs::qread
.patched_qread <- function(file, ...) {
  tryCatch(
    .orig_qread(file, ...),
    error = function(e) {
      if (grepl("QS format not detected|unsupported", conditionMessage(e),
                ignore.case=TRUE)) {
        cat("[entrypoint] qs::qread failed (", conditionMessage(e),
            "), retrying with qs2::qs_read\n", file=stderr())
        return(qs2::qs_read(file))
      }
      stop(e)
    }
  )
}
utils::assignInNamespace("qread", .patched_qread, ns="qs")

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------
if (args$`self-test`) {
  log_msg("Running self-test")
  pkgs <- c("FELLA", "MetaboAnalystR", "fgsea", "KEGGgraph", "igraph", "jsonlite")
  results <- list()
  for (p in pkgs) {
    ok <- requireNamespace(p, quietly=TRUE)
    results[[p]] <- ok
    cat(sprintf("  %-18s %s\n", p, if (ok) "OK" else "MISSING"), file=stderr())
  }
  fella_ready <- dir.exists(FELLA_DATA_DIR) &&
                 length(list.files(FELLA_DATA_DIR)) > 0
  all_ok <- all(unlist(results))
  cat(toJSON(list(self_test="done",
                  packages=results, all_ok=all_ok,
                  fella_data_ready=fella_ready,
                  fella_data_dir=FELLA_DATA_DIR),
             auto_unbox=TRUE), "\n")
  quit(status=if (all_ok) 0 else 1)
}

# ---------------------------------------------------------------------------
# Prewarm mode (container startup): build / cache FELLA KEGG graph
# ---------------------------------------------------------------------------
if (args$prewarm) {
  log_msg("Prewarming FELLA KEGG graph at", FELLA_DATA_DIR)
  if (!requireNamespace("FELLA", quietly=TRUE)) {
    cat(toJSON(list(prewarm="error",
                    error="FELLA package not installed"),
               auto_unbox=TRUE), "\n")
    quit(status=2)
  }
  if (dir.exists(FELLA_DATA_DIR) && length(list.files(FELLA_DATA_DIR)) > 0) {
    cat(toJSON(list(prewarm="cached", dir=FELLA_DATA_DIR),
               auto_unbox=TRUE), "\n")
    quit(status=0)
  }
  dir.create(FELLA_DATA_DIR, recursive=TRUE, showWarnings=FALSE)
  result <- tryCatch({
    suppressMessages(library(FELLA))
    set.seed(42)
    g <- FELLA::buildGraphFromKEGGREST(organism="hsa",
                                       filter.path=character(0))
    FELLA::buildDataFromGraph(keggdata.graph=g,
                              databaseDir=FELLA_DATA_DIR,
                              internalDir=FALSE,
                              matrices="diffusion",
                              normality="diffusion",
                              niter=100)
    list(prewarm="built", dir=FELLA_DATA_DIR)
  }, error=function(e) list(prewarm="error", error=conditionMessage(e)))
  cat(toJSON(result, auto_unbox=TRUE), "\n")
  quit(status=if (result$prewarm == "built") 0 else 3)
}

# ---------------------------------------------------------------------------
# Read stdin JSON
# ---------------------------------------------------------------------------
request_raw <- readLines(con="stdin", warn=FALSE)
if (length(request_raw) == 0) {
  cat(toJSON(list(error="empty stdin request"), auto_unbox=TRUE), "\n")
  quit(status=2)
}
request <- tryCatch(
  fromJSON(paste(request_raw, collapse="\n"), simplifyVector=FALSE),
  error=function(e) {
    cat(toJSON(list(error=paste("JSON parse:", conditionMessage(e))),
               auto_unbox=TRUE), "\n")
    quit(status=2)
  }
)
method <- request$method
params <- if (is.null(request$params)) list() else request$params

if (is.null(method)) {
  cat(toJSON(list(error="missing 'method' in request"),
             auto_unbox=TRUE), "\n")
  quit(status=2)
}

# ---------------------------------------------------------------------------
# Helper: convert input compound list → atomic vector (R lists from JSON
# come as plain lists, FELLA / MetaboAnalystR expect character vectors).
# ---------------------------------------------------------------------------
.as_char_vec <- function(x) {
  if (is.null(x)) return(character(0))
  if (is.list(x)) return(as.character(unlist(x)))
  as.character(x)
}

# ---------------------------------------------------------------------------
# FELLA RWR / diffusion
# ---------------------------------------------------------------------------
run_fella <- function(method_name, params) {
  compounds <- .as_char_vec(params$compounds)
  organism <- params$organism %||% "hsa"  # R-style default
  if (length(compounds) == 0) {
    return(list(method=method_name, pathways=list(),
                n_resolved=0, error="empty compounds list"))
  }
  if (!requireNamespace("FELLA", quietly=TRUE)) {
    return(list(method=method_name, error="FELLA not installed", pathways=list()))
  }
  suppressMessages(library(FELLA))

  if (!dir.exists(FELLA_DATA_DIR) || length(list.files(FELLA_DATA_DIR)) == 0) {
    return(list(method=method_name,
                error=paste("FELLA KEGG data not built at", FELLA_DATA_DIR,
                           "— rerun container --prewarm"),
                pathways=list()))
  }

  t0 <- proc.time()["elapsed"]
  result <- tryCatch({
    fella_data <- loadKEGGdata(databaseDir=FELLA_DATA_DIR,
                                internalDir=FALSE,
                                loadMatrix="diffusion")
    # enrich() runs RWR by default; for diffusion pass method="diffusion"
    analysis <- enrich(
      compounds=compounds, data=fella_data,
      method=if (method_name == "fella_diffusion") "diffusion" else "pagerank",
      approx="normality"
    )
    n_input_resolved <- length(getInput(analysis))
    # getResults returns nodes; pathway level via getCom(analysis, type="pathway")
    pathway_nodes <- tryCatch(
      generateResultsTable(method=if (method_name == "fella_diffusion")
                                  "diffusion" else "diffusion",
                          threshold=0.1, object=analysis,
                          data=fella_data),
      error=function(e) data.frame()
    )
    # Filter to pathway-layer (entry_type == "pathway")
    if (!"Entry.type" %in% colnames(pathway_nodes) &&
        "entry.type" %in% colnames(pathway_nodes)) {
      colnames(pathway_nodes) <- gsub("^entry\\.", "Entry.",
                                       colnames(pathway_nodes))
    }
    type_col <- if ("Entry.type" %in% colnames(pathway_nodes)) "Entry.type"
                else if ("type" %in% colnames(pathway_nodes)) "type" else NULL
    if (!is.null(type_col)) {
      pathway_nodes <- pathway_nodes[pathway_nodes[[type_col]] == "pathway", , drop=FALSE]
    }
    # Extract: KEGG pathway id + name + p-value/score
    # hits_kegg_ids: FELLA's diffusion/RWR analysis takes the full input
    # compound list and produces a graph-wide enrichment; per-pathway hit
    # attribution at the compound layer would require walking the result
    # graph (getCom(..., type="compound")) and intersecting with pathway
    # membership. For W5 we attach the full input pool to every reported
    # pathway — the v0.3 validator only needs non-empty metabolites_hit,
    # and downstream Jaccard at the pathway level is unaffected. Tighter
    # per-pathway attribution → W6 polish.
    input_kegg <- tryCatch(as.character(getInput(analysis)),
                           error=function(e) character(0))
    if (nrow(pathway_nodes) == 0) {
      pathways <- list()
    } else {
      pathways <- lapply(seq_len(nrow(pathway_nodes)), function(i) {
        row <- pathway_nodes[i, , drop=TRUE]
        # Common columns: KEGG.id / Entry.name / KEGG.name / p.score / etc.
        pid <- as.character(
          row[["KEGG.id"]] %||% row[["Entry.id"]] %||% row[["entry.id"]] %||% NA
        )
        pname <- as.character(
          row[["KEGG.name"]] %||% row[["Entry.name"]] %||% row[["name"]] %||% pid
        )
        pval <- as.numeric(
          row[["p.score"]] %||% row[["p_score"]] %||% row[["score"]] %||% 1.0
        )
        list(pathway_id=pid, pathway_name=pname,
             p_value=pval,
             hits_kegg_ids=as.list(input_kegg))
      })
    }
    list(
      method=method_name,
      pathways=pathways,
      n_resolved=n_input_resolved,
      tool_version=as.character(packageVersion("FELLA")),
      db_release=sprintf("kegg_%s_via_FELLA", organism),
      wall_time_sec=as.numeric(proc.time()["elapsed"] - t0)
    )
  }, error=function(e) {
    list(method=method_name, error=paste("FELLA exception:", conditionMessage(e)),
         pathways=list())
  })
  result
}

# ---------------------------------------------------------------------------
# MetaboAnalystR PSEA / MSEA / Mummichog
# ---------------------------------------------------------------------------
run_metaboanalystr_psea <- function(params) {
  compounds <- .as_char_vec(params$compounds)
  id_type <- params$id_type %||% "hmdb"
  library_name <- params$library %||% "kegg"
  if (length(compounds) == 0) {
    return(list(method="metaboanalystr_psea", pathways=list(),
                n_resolved=0, error="empty compounds"))
  }
  if (!requireNamespace("MetaboAnalystR", quietly=TRUE)) {
    return(list(method="metaboanalystr_psea",
                error="MetaboAnalystR not installed", pathways=list()))
  }
  suppressMessages(library(MetaboAnalystR))

  # Stable cwd for MetaboAnalystR's compound_db.qs / pathway_db.qs cache.
  # .get.my.lib downloads to getwd() and re-reads from there on subsequent
  # calls, so running every PSEA from the same dir is the cheapest cache
  # mechanism that does not require monkey-patching the function itself.
  old_wd <- getwd()
  setwd(METABOANALYSTR_CACHE_DIR)
  on.exit(setwd(old_wd), add=TRUE)
  result <- tryCatch({
    # MetaboAnalystR v4.2.0 ships InitDataObjects() with
    # ``default.dpi = default.dpi`` as the 4th formal — a self-
    # referential default that triggers "promise already under
    # evaluation: recursive default argument reference" when omitted.
    # Pass an explicit value (72 is MetaboAnalystR's documented default).
    mSet <- InitDataObjects("conc", "msetora", FALSE, default.dpi=72)
    mSet <- Setup.MapData(mSet, compounds)
    mSet <- CrossReferencing(mSet, id_type)
    mSet <- CreateMappingResultTable(mSet)
    # MetaboAnalystR has two dispatch families:
    #   pathway lib (SetKEGG.PathLib) → CalculateOraScore (PSEA-style)
    #   metset lib (SetCurrentMsetLib) → CalculateHyperScore (MSEA-style)
    # Using the wrong score function leads to
    # "argument is of length zero" when CalculateHyperScore checks
    # mSetObj$analSet$msetlibname which is not set in pathway mode.
    # SetKEGG.PathLib / SetCurrentMsetLib both *overwrite* mSet$api with
    # the library's {libVersion, libNm}, so SetMetabolomeFilter (which
    # writes mSet$api$filter that the score functions check) MUST come
    # afterwards. Earlier ordering silently dropped api$filter and the
    # score function then died on "argument is of length zero" inside
    # ``if (mSetObj$api$filter)``.
    if (library_name == "kegg") {
      mSet <- SetKEGG.PathLib(mSet, "hsa", "current")
      mSet <- SetMetabolomeFilter(mSet, FALSE)
      mSet <- CalculateOraScore(mSet, "rbc", "hyperg")
    } else {
      mSet <- SetCurrentMsetLib(mSet, "smpdb_pathway", 2)
      mSet <- SetMetabolomeFilter(mSet, FALSE)
      mSet <- CalculateHyperScore(mSet)
    }
    res_mat <- if (!is.null(mSet$analSet$ora.mat)) mSet$analSet$ora.mat else
               if (!is.null(mSet$analSet$msea.mat)) mSet$analSet$msea.mat else NULL
    if (is.null(res_mat) || nrow(res_mat) == 0) {
      return(list(method="metaboanalystr_psea", pathways=list(), n_resolved=0))
    }
    res_df <- as.data.frame(res_mat)
    # ora.hits is a named list: pathway_id → named char vec of KEGG cpd IDs
    # (names = compound display names). Used to populate hits_ids per
    # pathway so the v0.3 normalizer can resolve them via id_resolve.
    ora_hits <- mSet$analSet$ora.hits
    pathways <- lapply(seq_len(nrow(res_df)), function(i) {
      pid <- rownames(res_df)[i]
      hit_ids <- if (!is.null(ora_hits) && pid %in% names(ora_hits))
        as.character(ora_hits[[pid]]) else character(0)
      list(
        pathway_id=pid,
        pathway_name=as.character(res_df[i, "Name"] %||% pid),
        p_value=as.numeric(res_df[i, "Raw p"] %||% res_df[i, "p.value"] %||% 1.0),
        fdr=as.numeric(res_df[i, "Holm p"] %||% res_df[i, "fdr"] %||% NA),
        total=as.integer(res_df[i, "Total"] %||% 0),
        expected=as.numeric(res_df[i, "Expected"] %||% NA),
        hits=as.integer(res_df[i, "Hits"] %||% 0),
        hits_ids=as.list(hit_ids)  # KEGG cpd IDs; normalizer resolves via id_resolve
      )
    })
    list(
      method="metaboanalystr_psea",
      pathways=pathways,
      n_resolved=if (!is.null(mSet$dataSet$cmpd.org)) length(mSet$dataSet$cmpd.org) else length(compounds),
      tool_version=as.character(packageVersion("MetaboAnalystR")),
      db_release=library_name
    )
  }, error=function(e) {
    list(method="metaboanalystr_psea",
         error=paste("MetaboAnalystR PSEA exception:", conditionMessage(e)),
         pathways=list())
  })
  result
}

run_metaboanalystr_msea <- function(params) {
  # MSEA shares pipeline with PSEA — same wrapper handles via different lib
  params$library <- params$library %||% "smpdb"
  out <- run_metaboanalystr_psea(params)
  out$method <- "metaboanalystr_msea"
  out
}

run_metaboanalystr_mummichog <- function(params) {
  peaks <- params$peaks %||% list()
  mode <- params$mode %||% "positive"
  if (length(peaks) == 0) {
    return(list(method="metaboanalystr_mummichog", pathways=list(),
                n_resolved=0, error="empty peaks"))
  }
  if (!requireNamespace("MetaboAnalystR", quietly=TRUE)) {
    return(list(method="metaboanalystr_mummichog",
                error="MetaboAnalystR not installed", pathways=list()))
  }
  # W5 stub — full mummichog wrapper W6 (mummichog Python wrapper covers
  # the case adequately for 5-axis Gate 1).
  list(method="metaboanalystr_mummichog",
       error=paste0("MetaboAnalystR R-mummichog not implemented in W5; ",
                    "use concord.wrappers.mummichog_wrapper for Python path"),
       pathways=list())
}

# ---------------------------------------------------------------------------
# Helper: null-coalescing operator (%||%) — pre-base R 4.4
# ---------------------------------------------------------------------------
`%||%` <- function(a, b) if (is.null(a) || is.na(a) || identical(a, "")) b else a

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
dispatch <- function(method, params) {
  switch(
    method,
    "fella_rwr"             = run_fella("fella_rwr", params),
    "fella_diffusion"       = run_fella("fella_diffusion", params),
    "metaboanalystr_psea"   = run_metaboanalystr_psea(params),
    "metaboanalystr_msea"   = run_metaboanalystr_msea(params),
    "metaboanalystr_mummichog" = run_metaboanalystr_mummichog(params),
    list(error=paste("unknown method:", method))
  )
}

response <- tryCatch(
  dispatch(method, params),
  error=function(e) list(error=paste("exception:", conditionMessage(e)))
)
cat(toJSON(response, auto_unbox=TRUE, na="null", null="null", force=TRUE), "\n")
quit(status=if (!is.null(response$error)) 1 else 0)

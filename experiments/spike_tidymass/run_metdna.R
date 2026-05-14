# Minimal MetDNA2 wrapper for the deployment-feasibility spike.
# Reads a Spectrum-shaped JSON, runs MetDNA2 identification + network
# propagation, writes a structured JSON result.
#
# This is a SPIKE — not production. Single-spectrum convenience wrapper.
# Real MetDNA2 expects a peak table over many features; here we synthesise
# a 1-feature peak table just to exercise the pipeline.

suppressPackageStartupMessages({
  library(optparse)
  library(jsonlite)
  library(MetDNA2)
})

opt_parser <- OptionParser(option_list = list(
  make_option("--input",  type = "character", help = "input JSON path"),
  make_option("--output", type = "character", help = "output JSON path"),
  make_option("--organism", type = "character", default = "hsa",
              help = "KEGG organism code [default %default]"),
  make_option("--polarity", type = "character", default = "positive",
              help = "ion mode [default %default]")
))
opts <- parse_args(opt_parser)

if (is.null(opts$input) || is.null(opts$output)) {
  stop("--input and --output required")
}

# ---------------------------------------------------------------------------
# Input contract: see schemas/common.py::Spectrum
# {
#   "spectrum_id": str,
#   "precursor_mz": float,
#   "ion_mode": "positive" | "negative",
#   "adduct": str,
#   "peaks": [[mz, intensity], ...]
# }
# ---------------------------------------------------------------------------
spec <- fromJSON(opts$input, simplifyVector = FALSE)

# TODO[D3]: synthesise minimal MS1 peak table + MS2 mgf temp file in
# the format MetDNA2 expects, then call its top-level identify*() entry.
# Exact API surface to be confirmed during D3 (read MetDNA2 vignette).
# Placeholder that will fail loudly so we know the wiring is reached:
result <- list(
  status         = "spike_placeholder",
  spectrum_id    = spec$spectrum_id,
  organism       = opts$organism,
  polarity       = opts$polarity,
  identifications = list(),     # to be populated in D3
  network_propagated = list(),  # to be populated in D3
  provenance     = list(
    metdna2_version = as.character(packageVersion("MetDNA2")),
    r_version       = R.version.string
  )
)

write_json(result, opts$output, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("[run_metdna.R] wrote %s\n", opts$output))

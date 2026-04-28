# sirius_annotate

Use this tool when you need to verify a peak-level fragmentation claim, or
when the molecular formula of a precursor should be confirmed by a dedicated
fragmentation-tree algorithm.

The tool supports positive and negative ionization. Pass through the
preprocessed `Spectrum` unchanged, including its adduct (`[M+H]+`, `[M-H]-`,
etc.) and `ionization_mode`.

Do not call this tool for simple precursor mass matching; use
`candidate_prefilter` for that. Do not call it when the spectrum has fewer
than 5 peaks, because SIRIUS may fail or produce an unreliable tree.

The response contains `lookup_fragment(mz, tolerance_ppm)`. It returns a
`FragmentAnnotation` when SIRIUS placed a tree node within tolerance of the
requested m/z, otherwise `None`. `None` means SIRIUS found no tree fragment at
that m/z in this run; it does not mean the fragment is chemically impossible.

Failure modes include timeouts on large molecules or difficult spectra, no
formula found for noisy spectra, malformed SIRIUS output, missing local SIRIUS
binary, and SIRIUS builds that require login before compound tools run.

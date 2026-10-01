{
  description = "examhub-pipeline dev shell: the pipeline and the Hugo site";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        name = "examhub-pipeline";

        packages = with pkgs; [
          uv # venv / dependency driver
          hugo # builds and previews site/
          nodejs # site/tools/check-links.mjs
          geckodriver # headless Firefox for JS-rendered feeds (CI uses the runner image's)

          (python311.withPackages (ps: with ps; [ pip setuptools pytest ]))

          # PDF text-layer inspection, for debugging a notice that came out
          # as an image-only scan.
          poppler-utils

          # OCR. tesseract carries the English data used for the image-only
          # state PSC notices; ocrmypdf produces a real text layer, which is
          # what extract.py prefers over raw pytesseract.
          # The tessdata files (eng, and anything else the operator adds to
          # TESSDATA_PREFIX) ship inside the tesseract derivation, so there
          # are no separate tesseract_eng attributes to list -- and an
          # unknown attribute fails the whole shell rather than one package.
          tesseract
          ocrmypdf

          # Debugging a slow or rate-limiting gov host
          curl
          jq
          ripgrep
          git
          gh # GitHub: repo, workflow runs, secrets; also git's login helper
        ];

        # Deliberately free of ${...}. A literal ${ inside a nix '' string
        # has to be written ''${, and that escape next to a closing double
        # quote is parsed as a string concatenation followed by an attrset --
        # a confusing error for an ordinary line of shell. The conditionals
        # below say the same thing without any escaping at all.
        shellHook = ''
          if [ -z "$HF_HOME" ]; then
            export HF_HOME="$HOME/.cache/huggingface"
          fi
          # Only src/: the packages live in uv's .venv. The nix Python tools
          # (ocrmypdf) put their own libraries on PYTHONPATH, built for another
          # Python, and those break the venv's imports (lxml.etree).
          export PYTHONPATH="$PWD/src"
          echo "examhub-pipeline: python $(python3 --version 2>/dev/null | cut -d" " -f2), tesseract $(tesseract --version 2>/dev/null | head -1 | cut -d" " -f2)"
          echo "  Laya weights cache: $HF_HOME  (CPU-only box: ~800MB per checkpoint)"
          echo "  The default checkpoint is typed-decisions (ModernBERT-large, 421M),"
          echo "  not the 2.2x-faster multilingual one. See README, validator section."
          echo "  Site preview: (cd site && hugo server)"
        '';
      };
    };
}

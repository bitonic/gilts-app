with import <nixos-unstable> {};
mkShell {
  buildInputs = [
    (python3.withPackages (p: [
      p.python-dateutil
      p.openpyxl
      p.xlrd
      p.requests
      p.tabulate
      p.matplotlib
      p.ofxtools
      p.python-lsp-server
      p.pytz
      p.scipy
      p.pandas
    ]))
    sqlite
    rlwrap
    libreoffice
    jq
    claude-code
    # gemini-cli
  ];
}

{
  description = "Flake for Volatility Plugins";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    espidf.url = "github:hnaderi/espidf-nix";
  };

  outputs = { self, nixpkgs, espidf }: 
    let pkgs = import nixpkgs {
      system = "x86_64-linux";
      overlays = [ espidf.overlays.default ];
      config.allowUnfree = true;
      };
    in {
      devShells.x86_64-linux.default =
        pkgs.mkShell {
          buildInputs = [
            pkgs.volatility3
            pkgs.esp-idf
            pkgs.clang-tools
            pkgs.git
            (pkgs.python3.withPackages (ps: [
              ps.pefile
              ps.capstone
              ps.yara-python
            ]))
          ];
        };
    };
}


# Homebrew formula for the token signing host.
#
# Lives here as the source of truth; the tap it gets copied into is
# resilient-tech/homebrew-tap, as Casks/../Formula/docsigner-host.rb:
#
#     brew install resilient-tech/tap/docsigner-host
#
# A formula rather than a cask, on purpose. Homebrew only applies the
# com.apple.quarantine attribute to casks (Library/Homebrew/cask/quarantine.rb),
# so a formula-installed binary runs with no Gatekeeper prompt and no Developer
# ID certificate. That is the whole reason the host ships this way.
#
# It installs the released x86_64 archive instead of building from source. An
# arm64 build would be the wrong binary: some Indian CA middleware ships x86_64
# only, and an arm64 process cannot load an x86_64-only PKCS#11 module, while
# the x86_64 build reaches every driver through Rosetta. The reasoning in full
# is at the top of .github/workflows/release.yml. Do not switch this to a
# build-from-source formula to make it look more idiomatic.
class DocsignerHost < Formula
  desc "Signs PDF hashes with a DSC token, over browser native messaging"
  homepage "https://github.com/resilient-tech/docsigner"
  # The version is spelled out in the url rather than interpolated. `brew style`
  # requires url before version, and a url declared first cannot interpolate a
  # version that is not set yet. So the release workflow rewrites all three of
  # these lines; the cask, which needs no such ordering, interpolates and gets
  # rewritten in two.
  url "https://github.com/resilient-tech/docsigner/releases/download/v0.2.0/docsigner-host-0.2.0-macos-x86_64.tar.gz"
  version "0.2.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "Apache-2.0"

  def install
    libexec.install Dir["docsigner-host-#{version}-macos-x86_64/*"]
    bin.install_symlink libexec/"docsigner-host"
  end

  # Registering with the browsers needs the extension ID, which brew has no way
  # to know, so that step stays a one-liner the user runs. install.sh honours
  # DOCSIGNER_BINARY, which is how it finds the copy brew just placed.
  def caveats
    <<~EOS
      Register the host with your browsers, using your extension's ID:

        DOCSIGNER_BINARY=#{opt_libexec}/docsigner-host \\
            #{opt_libexec}/packaging/install.sh <chrome-extension-id>

      Your DSC token's own PKCS#11 driver still has to be installed
      separately. It is hardware middleware and cannot ride inside this
      binary.
    EOS
  end

  test do
    assert_match "\"protocolVersion\": 1", shell_output("#{bin}/docsigner-host version")
  end
end

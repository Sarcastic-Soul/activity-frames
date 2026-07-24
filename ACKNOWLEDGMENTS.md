# Acknowledgments

The default capture engine provisioned by `aframes record` is
[nocta-recorder](https://github.com/nossa-y/nocta-recorder), an MIT-licensed
screen + activity recorder. It is downloaded on demand from GitHub Releases and
is not bundled with this package. The compiler itself is engine-agnostic: any
capture system writing a compatible SQLite schema works via `$AFRAMES_DB`.

#!/usr/bin/env bats

setup() {
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  BIN_DIR="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$WORKSPACE" "$BIN_DIR"
  cat > "$BIN_DIR/mst" <<'SH'
#!/usr/bin/env sh
exit 0
SH
  chmod +x "$BIN_DIR/mst"
}

@test "AC-005 user shell mst confirm does not trigger hook core BLOCK" {
  run env -u MST_HOOK_CONTEXT PATH="$BIN_DIR:$PATH" bash -c "cd '$WORKSPACE' && mst confirm cf_user"

  [ "$status" -eq 0 ]
  [[ "$output" != *"[core-block]"* ]]
  [ ! -e "$WORKSPACE/.gran-maestro/sessions" ]
}

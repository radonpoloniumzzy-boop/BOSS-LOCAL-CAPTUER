(function (globalThis) {
  globalThis.BossLocalWebIntake = {
    ...globalThis.BossLocalWebIntakeIdentity,
    ...globalThis.BossLocalWebIntakeStorage,
    ...globalThis.BossLocalWebIntakeUi,
    ...globalThis.BossLocalWebIntakeSender,
  };
})(globalThis);

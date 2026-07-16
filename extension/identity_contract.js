(function installBossIdentityContract(globalScope) {
  if (globalScope.__bossLocalIdentityContract) {
    return;
  }

  globalScope.__bossLocalIdentityContract = Object.freeze({
    trustedPlatformUidAttributes: Object.freeze([
      "data-candidate-id",
      "data-encrypt-geek-id",
      "data-encrypt-uid",
      "data-geek-id",
      "data-geekid",
    ]),
  });
})(globalThis);

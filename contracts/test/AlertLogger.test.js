// test/AlertLogger.test.js
//
// Hardhat + chai tests for the AlertLogger contract (ethers v6).

const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AlertLogger", function () {
  let alertLogger;
  let owner;
  let writer;
  let stranger;

  // Sample alert fixture values.
  const alertHash = ethers.keccak256(ethers.toUtf8Bytes("alert-1"));
  const token = "MNT";
  const amountUsd = 12345n;
  const txHash = ethers.keccak256(ethers.toUtf8Bytes("tx-1"));

  beforeEach(async function () {
    [owner, writer, stranger] = await ethers.getSigners();
    const AlertLogger = await ethers.getContractFactory("AlertLogger");
    alertLogger = await AlertLogger.deploy();
    await alertLogger.waitForDeployment();
  });

  it("sets the deployer as owner and authorizes them", async function () {
    expect(await alertLogger.owner()).to.equal(owner.address);
    expect(await alertLogger.authorized(owner.address)).to.equal(true);
  });

  it("lets the owner logAlert and emits AlertLogged with correct args", async function () {
    await expect(alertLogger.logAlert(alertHash, token, amountUsd, txHash))
      .to.emit(alertLogger, "AlertLogged")
      .withArgs(
        alertHash,
        token,
        amountUsd,
        txHash,
        owner.address,
        // timestamp is dynamic; match any value.
        (ts) => typeof ts === "bigint" && ts > 0n
      );
  });

  it("stores and returns the alert via getAlert", async function () {
    await alertLogger.logAlert(alertHash, token, amountUsd, txHash);

    const stored = await alertLogger.getAlert(alertHash);
    expect(stored.alertHash).to.equal(alertHash);
    expect(stored.token).to.equal(token);
    expect(stored.amountUsd).to.equal(amountUsd);
    expect(stored.txHash).to.equal(txHash);
    expect(stored.reporter).to.equal(owner.address);
    expect(stored.timestamp).to.be.greaterThan(0n);
  });

  it("increments totalAlerts and getAlertCount", async function () {
    expect(await alertLogger.totalAlerts()).to.equal(0n);
    expect(await alertLogger.getAlertCount()).to.equal(0n);

    await alertLogger.logAlert(alertHash, token, amountUsd, txHash);
    expect(await alertLogger.totalAlerts()).to.equal(1n);
    expect(await alertLogger.getAlertCount()).to.equal(1n);

    const alertHash2 = ethers.keccak256(ethers.toUtf8Bytes("alert-2"));
    await alertLogger.logAlert(alertHash2, "USDC", 500n, txHash);
    expect(await alertLogger.totalAlerts()).to.equal(2n);
    expect(await alertLogger.getAlertCount()).to.equal(2n);
  });

  it("reverts when a non-authorized account tries to logAlert", async function () {
    await expect(
      alertLogger.connect(stranger).logAlert(alertHash, token, amountUsd, txHash)
    ).to.be.revertedWith("AlertLogger: caller is not authorized");
  });

  it("lets the owner setAuthorized and the new writer can log", async function () {
    // Writer is not authorized initially.
    await expect(
      alertLogger.connect(writer).logAlert(alertHash, token, amountUsd, txHash)
    ).to.be.revertedWith("AlertLogger: caller is not authorized");

    // Owner authorizes the writer.
    await expect(alertLogger.setAuthorized(writer.address, true))
      .to.emit(alertLogger, "AuthorizationChanged")
      .withArgs(writer.address, true);
    expect(await alertLogger.authorized(writer.address)).to.equal(true);

    // Now the writer can log successfully.
    await expect(
      alertLogger.connect(writer).logAlert(alertHash, token, amountUsd, txHash)
    ).to.emit(alertLogger, "AlertLogged");

    const stored = await alertLogger.getAlert(alertHash);
    expect(stored.reporter).to.equal(writer.address);
  });

  it("reverts on duplicate alertHash", async function () {
    await alertLogger.logAlert(alertHash, token, amountUsd, txHash);
    await expect(
      alertLogger.logAlert(alertHash, token, amountUsd, txHash)
    ).to.be.revertedWith("AlertLogger: alert already exists");
  });

  it("restricts setAuthorized to the owner", async function () {
    await expect(
      alertLogger.connect(stranger).setAuthorized(stranger.address, true)
    ).to.be.revertedWith("AlertLogger: caller is not the owner");
  });

  it("transfers ownership and rejects the zero address", async function () {
    await expect(
      alertLogger.transferOwnership(ethers.ZeroAddress)
    ).to.be.revertedWith("AlertLogger: new owner is the zero address");

    await expect(alertLogger.transferOwnership(writer.address))
      .to.emit(alertLogger, "OwnershipTransferred")
      .withArgs(owner.address, writer.address);
    expect(await alertLogger.owner()).to.equal(writer.address);
  });
});

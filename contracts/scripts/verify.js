// scripts/verify.js
//
// Verifies the deployed AlertLogger contract on the Mantle block explorer.
//
// Usage:
//   npx hardhat run scripts/verify.js --network mantleTestnet
//
// The address is read from deployments/<network>.json, or overridden by the
// CONTRACT_ADDRESS environment variable. The constructor takes no arguments.

const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const networkName = hre.network.name;

  // Resolve the contract address: env override first, then deployments file.
  let address = process.env.CONTRACT_ADDRESS;

  if (!address) {
    const deploymentFile = path.join(__dirname, "..", "deployments", `${networkName}.json`);
    if (!fs.existsSync(deploymentFile)) {
      throw new Error(
        `No deployment found for network "${networkName}". ` +
          `Set CONTRACT_ADDRESS or deploy first (expected ${deploymentFile}).`
      );
    }
    const info = JSON.parse(fs.readFileSync(deploymentFile, "utf8"));
    address = info.address;
  }

  if (!address) {
    throw new Error("Could not determine the contract address to verify.");
  }

  console.log(`Verifying AlertLogger at ${address} on network ${networkName}...`);

  try {
    await hre.run("verify:verify", {
      address,
      constructorArguments: [],
    });
    console.log("Verification successful.");
  } catch (error) {
    const message = (error && error.message) || String(error);
    if (message.toLowerCase().includes("already verified")) {
      console.log("Contract is already verified.");
    } else {
      console.error("Verification failed:");
      console.error(message);
      process.exitCode = 1;
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

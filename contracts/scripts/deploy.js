// scripts/deploy.js
//
// Deploys the AlertLogger contract using Hardhat + ethers v6.
//
// Usage:
//   npx hardhat run scripts/deploy.js --network mantleTestnet
//
// After deployment, wire the printed address into the Python backend's .env:
//   ALERT_LOGGER_CONTRACT_ADDRESS=<deployed address>
//   ALERT_LOGGER_PRIVATE_KEY=<the writer key authorized to call logAlert>
//   ENABLE_ONCHAIN_LOGGING=true
//
// The constructor takes no arguments; the deployer becomes the owner and is
// authorized to call logAlert by default.

const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const networkName = hre.network.name;
  console.log(`Deploying AlertLogger to network: ${networkName}`);

  const [deployer] = await hre.ethers.getSigners();
  if (deployer) {
    console.log(`Deployer address: ${deployer.address}`);
  }

  const AlertLogger = await hre.ethers.getContractFactory("AlertLogger");
  const alertLogger = await AlertLogger.deploy();

  // ethers v6: wait for the deployment transaction to be mined.
  await alertLogger.waitForDeployment();

  const address = await alertLogger.getAddress();
  console.log(`AlertLogger deployed to: ${address}`);
  console.log(`Network: ${networkName}`);

  // Persist the deployed address to deployments/<network>.json.
  const deploymentsDir = path.join(__dirname, "..", "deployments");
  if (!fs.existsSync(deploymentsDir)) {
    fs.mkdirSync(deploymentsDir, { recursive: true });
  }

  const deploymentInfo = {
    network: networkName,
    address,
    deployer: deployer ? deployer.address : null,
    deployedAt: new Date().toISOString(),
  };

  const outFile = path.join(deploymentsDir, `${networkName}.json`);
  fs.writeFileSync(outFile, JSON.stringify(deploymentInfo, null, 2));
  console.log(`Deployment info written to: ${outFile}`);

  console.log("\nNext steps:");
  console.log("  1. Set ALERT_LOGGER_CONTRACT_ADDRESS in the backend .env to:");
  console.log(`       ${address}`);
  console.log("  2. Set ALERT_LOGGER_PRIVATE_KEY and ENABLE_ONCHAIN_LOGGING=true.");
  console.log("  3. Verify the contract with: npx hardhat run scripts/verify.js --network " + networkName);
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

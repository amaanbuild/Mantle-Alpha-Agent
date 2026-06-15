require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const PRIVATE_KEY = process.env.PRIVATE_KEY;
const accounts = PRIVATE_KEY ? [PRIVATE_KEY] : [];

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },

  // The contract source (AlertLogger.sol) lives in this base directory, so point
  // Hardhat's `sources` path at "./" instead of the default "./contracts".
  paths: {
    sources: "./",
  },

  networks: {
    mantleTestnet: {
      url: process.env.MANTLE_TESTNET_RPC || "https://rpc.sepolia.mantle.xyz",
      chainId: 5003,
      accounts,
    },
    mantleMainnet: {
      url: process.env.MANTLE_RPC || "https://rpc.mantle.xyz",
      chainId: 5000,
      accounts,
    },
  },

  // Contract verification configuration for Mantle's Blockscout-based explorers.
  etherscan: {
    apiKey: {
      mantleTestnet: process.env.MANTLE_EXPLORER_API_KEY || "",
      mantleMainnet: process.env.MANTLE_EXPLORER_API_KEY || "",
    },
    customChains: [
      {
        network: "mantleTestnet",
        chainId: 5003,
        urls: {
          apiURL: "https://explorer.sepolia.mantle.xyz/api",
          browserURL: "https://explorer.sepolia.mantle.xyz",
        },
      },
      {
        network: "mantleMainnet",
        chainId: 5000,
        urls: {
          apiURL: "https://explorer.mantle.xyz/api",
          browserURL: "https://explorer.mantle.xyz",
        },
      },
    ],
  },
};

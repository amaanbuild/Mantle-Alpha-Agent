# Mantle Alert Logger

A Hardhat-based Solidity package for `AlertLogger`, an on-chain registry that records alpha alerts emitted by the Mantle Alpha Agent backend. Deployable on Mantle testnet (Sepolia) and mainnet.

## Contract

`AlertLogger.sol` (Solidity `^0.8.24`) exposes the write entrypoint consumed by the Python backend:

```solidity
function logAlert(bytes32 alertHash, string token, uint256 amountUsd, bytes32 txHash) external
```

- Each alert is keyed by a unique `alertHash` and is immutable once written (duplicate hashes revert).
- Write access is gated by an `authorized` allow-list. The deployer (`owner`) is authorized by default and can grant/revoke other writers via `setAuthorized`.
- Read with `getAlert(alertHash)` and `getAlertCount()`; iterate historical hashes via the public `alertHashes` array.

## Prerequisites

- Node.js 18+ and npm.
- A funded account on the target Mantle network (get testnet MNT from the Mantle Sepolia faucet).

## Setup

```bash
cd "c:\Users\amaan\Desktop\Mantle Alpha Agent\contracts"
npm install
cp .env.example .env   # then fill in PRIVATE_KEY and (optionally) the RPC/explorer values
```

Environment variables (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `PRIVATE_KEY` | Deployer / authorized writer key. |
| `MANTLE_TESTNET_RPC` | Mantle Sepolia RPC (defaults to `https://rpc.sepolia.mantle.xyz`). |
| `MANTLE_RPC` | Mantle mainnet RPC (defaults to `https://rpc.mantle.xyz`). |
| `MANTLE_EXPLORER_API_KEY` | Explorer API key for verification (Blockscout usually accepts any value). |

## Compile

```bash
npx hardhat compile
```

## Test

Tests run against Hardhat's in-process network (no RPC or funds required):

```bash
npx hardhat test
```

## Deploy to Mantle testnet

```bash
npx hardhat run scripts/deploy.js --network mantleTestnet
```

The script prints the deployed address and writes it to `deployments/mantleTestnet.json`.

For mainnet:

```bash
npx hardhat run scripts/deploy.js --network mantleMainnet
```

## Verify

The address is read automatically from `deployments/<network>.json` (or override with `CONTRACT_ADDRESS`):

```bash
npx hardhat run scripts/verify.js --network mantleTestnet
```

## Wire into the Python backend

After deploying, set the following in the backend's `.env`:

```bash
ALERT_LOGGER_CONTRACT_ADDRESS=<deployed address from deploy output>
ALERT_LOGGER_PRIVATE_KEY=<private key of an authorized writer>
ENABLE_ONCHAIN_LOGGING=true
```

The backend calls `logAlert(bytes32,string,uint256,bytes32)` exactly as defined here. If you use a writer key that is not the deployer, first authorize it on-chain:

```bash
# from the owner account, e.g. via a hardhat console or script:
#   alertLogger.setAuthorized(<writerAddress>, true)
```

## Network reference

| Network | Chain ID | Default RPC | Explorer |
| --- | --- | --- | --- |
| Mantle Sepolia testnet | 5003 | `https://rpc.sepolia.mantle.xyz` | `https://explorer.sepolia.mantle.xyz` |
| Mantle mainnet | 5000 | `https://rpc.mantle.xyz` | `https://explorer.mantle.xyz` |

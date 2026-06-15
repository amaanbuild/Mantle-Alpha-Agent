// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AlertLogger
/// @author Mantle Alpha Agent
/// @notice On-chain registry for alpha alerts emitted by the Mantle Alpha Agent backend.
///         Each alert is keyed by a unique `alertHash` and is immutable once written.
/// @dev    Write access is gated by an `authorized` allow-list controlled by the `owner`.
///         The owner is authorized by default. The `logAlert` signature is consumed
///         verbatim by the Python backend, so its parameter order and types must not change.
contract AlertLogger {
    // -------------------------------------------------------------------------
    // Types
    // -------------------------------------------------------------------------

    /// @notice A single logged alert record.
    /// @param alertHash Unique identifier for the alert (also the storage key).
    /// @param token     Symbol or address string of the token the alert concerns.
    /// @param amountUsd Notional USD amount associated with the alert (integer USD, caller-defined scaling).
    /// @param txHash    The originating transaction hash that triggered the alert.
    /// @param timestamp Block timestamp at which the alert was logged.
    /// @param reporter  Address that submitted the alert.
    struct Alert {
        bytes32 alertHash;
        string token;
        uint256 amountUsd;
        bytes32 txHash;
        uint256 timestamp;
        address reporter;
    }

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------

    /// @notice The contract owner, able to manage the authorized writer set and ownership.
    address public owner;

    /// @notice Allow-list of addresses permitted to call {logAlert}.
    mapping(address => bool) public authorized;

    /// @notice Stored alerts keyed by their unique `alertHash`.
    mapping(bytes32 => Alert) public alerts;

    /// @notice Append-only list of every `alertHash` ever logged, in insertion order.
    bytes32[] public alertHashes;

    /// @notice Total number of alerts logged.
    uint256 public totalAlerts;

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------

    /// @notice Emitted whenever a new alert is successfully logged.
    /// @param alertHash Unique identifier for the alert (indexed for filtering).
    /// @param token     Symbol or address string of the token the alert concerns.
    /// @param amountUsd Notional USD amount associated with the alert.
    /// @param txHash    The originating transaction hash (indexed for filtering).
    /// @param reporter  Address that submitted the alert (indexed for filtering).
    /// @param timestamp Block timestamp at which the alert was logged.
    event AlertLogged(
        bytes32 indexed alertHash,
        string token,
        uint256 amountUsd,
        bytes32 indexed txHash,
        address indexed reporter,
        uint256 timestamp
    );

    /// @notice Emitted when an address is granted or revoked write access.
    /// @param writer The address whose authorization changed.
    /// @param ok     The new authorization state (true = authorized).
    event AuthorizationChanged(address indexed writer, bool ok);

    /// @notice Emitted when ownership of the contract is transferred.
    /// @param previousOwner The prior owner address.
    /// @param newOwner      The new owner address.
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // -------------------------------------------------------------------------
    // Modifiers
    // -------------------------------------------------------------------------

    /// @notice Restricts a function to the contract owner.
    modifier onlyOwner() {
        require(msg.sender == owner, "AlertLogger: caller is not the owner");
        _;
    }

    /// @notice Restricts a function to addresses on the authorized writer allow-list.
    modifier onlyAuthorized() {
        require(authorized[msg.sender], "AlertLogger: caller is not authorized");
        _;
    }

    // -------------------------------------------------------------------------
    // Constructor
    // -------------------------------------------------------------------------

    /// @notice Deploys the contract, setting the deployer as owner and authorizing them.
    constructor() {
        owner = msg.sender;
        authorized[msg.sender] = true;
        emit OwnershipTransferred(address(0), msg.sender);
        emit AuthorizationChanged(msg.sender, true);
    }

    // -------------------------------------------------------------------------
    // Write functions
    // -------------------------------------------------------------------------

    /// @notice Logs a new alert on-chain. Reverts if an alert with the same `alertHash` already exists.
    /// @dev    Signature must match the Python backend ABI exactly:
    ///         `logAlert(bytes32,string,uint256,bytes32)`.
    /// @param alertHash Unique identifier for the alert (used as the storage key).
    /// @param token     Symbol or address string of the token the alert concerns.
    /// @param amountUsd Notional USD amount associated with the alert.
    /// @param txHash    The originating transaction hash that triggered the alert.
    function logAlert(
        bytes32 alertHash,
        string calldata token,
        uint256 amountUsd,
        bytes32 txHash
    ) external onlyAuthorized {
        require(alerts[alertHash].timestamp == 0, "AlertLogger: alert already exists");

        alerts[alertHash] = Alert({
            alertHash: alertHash,
            token: token,
            amountUsd: amountUsd,
            txHash: txHash,
            timestamp: block.timestamp,
            reporter: msg.sender
        });

        alertHashes.push(alertHash);
        totalAlerts += 1;

        emit AlertLogged(alertHash, token, amountUsd, txHash, msg.sender, block.timestamp);
    }

    /// @notice Grants or revokes write access for an address.
    /// @param writer The address to update.
    /// @param ok     True to authorize, false to revoke.
    function setAuthorized(address writer, bool ok) external onlyOwner {
        authorized[writer] = ok;
        emit AuthorizationChanged(writer, ok);
    }

    /// @notice Transfers ownership of the contract to a new address.
    /// @dev    The new owner is not automatically added to the authorized writer set.
    /// @param newOwner The address of the new owner. Must be non-zero.
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "AlertLogger: new owner is the zero address");
        address previousOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }

    // -------------------------------------------------------------------------
    // View functions
    // -------------------------------------------------------------------------

    /// @notice Returns the full stored record for a given alert hash.
    /// @param alertHash The unique identifier of the alert to fetch.
    /// @return The stored {Alert} struct (zero-valued if not found).
    function getAlert(bytes32 alertHash) external view returns (Alert memory) {
        return alerts[alertHash];
    }

    /// @notice Returns the total number of alerts logged.
    /// @return The current value of {totalAlerts}.
    function getAlertCount() external view returns (uint256) {
        return totalAlerts;
    }
}

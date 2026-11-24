// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Burnable} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title QicasCredit — transferable ERC-20 carbon credit (QICAS Phase 5)
/// @notice 1 token = 1 g CO2e of NET verified saving (decimals = 0). Only holders of MINTER_ROLE (the market
///         contract, CarbonScheduleMarketV3) can mint. `retire` burns credits and emits `Retired`, so a claimed
///         saving cannot be counted twice WITHIN THIS LEDGER (a plain transfer does not retire anything).
/// @dev OpenZeppelin 5.4.0, vendored in chain/vendor/openzeppelin (no network at compile time).
///      Once the admin renounces DEFAULT_ADMIN_ROLE, no account can ever be granted MINTER_ROLE again.
contract QicasCredit is ERC20, ERC20Burnable, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    event Retired(address indexed holder, address indexed beneficiary, uint256 amount, string reason);

    constructor(address admin) ERC20("QICAS Carbon Credit", "QCC") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function decimals() public pure override returns (uint8) {
        return 0;
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }

    /// @notice Burn `amount` of the caller's credits on behalf of `beneficiary` (offset claim).
    function retire(uint256 amount, address beneficiary, string calldata reason) external {
        _burn(_msgSender(), amount);
        emit Retired(_msgSender(), beneficiary, amount, reason);
    }
}

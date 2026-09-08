import { VaultManager } from '../index.js';

class GlobalState {
  constructor() {
    this.manager = null;
  }

  /**
   * Initializes the manager instance for a specific file path.
   * @param {string} vaultPath 
   */
  initManager(vaultPath) {
    if (!this.manager || this.manager.filePath !== vaultPath) {
      this.manager = new VaultManager(vaultPath);
    }
  }

  /**
   * Returns the active VaultManager instance.
   * @returns {VaultManager | null}
   */
  getManager() {
    return this.manager;
  }

  /**
   * Locks and destroys the active manager instance.
   */
  clearManager() {
    if (this.manager) {
      try {
        this.manager.lock();
      } catch (e) {
        // Ignore locking errors during cleanup
      }
    }
    this.manager = null;
  }
}

export const vaultState = new GlobalState();

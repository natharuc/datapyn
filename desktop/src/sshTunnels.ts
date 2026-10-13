import type { ConnectionsController } from "./connections";
import type { SshConnectionOptions } from "./workspace";

export interface SavedSshTunnel {
  id: string;
  name: string;
  config: SshConnectionOptions;
  has_password: boolean;
  has_passphrase: boolean;
  created_at?: string;
  updated_at?: string;
}

/** Keep tunnel secrets in the save request; catalog snapshots contain public metadata. */
export function saveSshTunnel(controller: ConnectionsController, name: string, config: SshConnectionOptions, id?: string) {
  const { password, passphrase, ...publicConfig } = config;
  return controller.mutate<SavedSshTunnel>("ssh.tunnels.save", {
    tunnel: { ...(id ? { id } : {}), name: name.trim(), config: { ...publicConfig, enabled: true } },
    ...(password ? { password } : {}), ...(passphrase ? { passphrase } : {}), save_credentials: true,
  });
}

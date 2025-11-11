interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_IPFS_API?: string;
  readonly VITE_IPFS_GATEWAY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

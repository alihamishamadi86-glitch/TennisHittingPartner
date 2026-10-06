"use client";

import { useRef, useState, type ChangeEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";

const ACCEPT = "image/jpeg,image/png,image/webp";

/** Uploads straight to storage with a signed URL, then asks the API to attach the object. */
export function PhotoUpload({
  name,
  initialUrl,
  onUploaded,
}: {
  name: string;
  initialUrl: string | null;
  onUploaded?: (url: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState(initialUrl);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setPending(true);
    setError(undefined);
    try {
      const target = await apiBrowser.POST("/me/photo/upload-url", {
        body: { content_type: file.type, size: file.size },
      });
      if (!target.data) throw new Error(errorMessage(target.error));

      const upload = await fetch(target.data.upload_url, {
        method: target.data.method,
        headers: target.data.headers,
        body: file,
      });
      if (!upload.ok) throw new Error("Upload failed — please try again.");

      const attached = await apiBrowser.PUT("/me/photo", { body: { object_name: target.data.object_name } });
      if (!attached.data?.avatar_url) throw new Error(errorMessage(attached.error));
      setUrl(attached.data.avatar_url);
      onUploaded?.(attached.data.avatar_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Profile photo</span>
      <div className="flex items-center gap-4">
        <Avatar src={url} name={name} size={72} />
        <div className="flex flex-col gap-1">
          <Button type="button" variant="secondary" onClick={() => input.current?.click()} disabled={pending}>
            {pending ? "Uploading…" : url ? "Change photo" : "Upload photo"}
          </Button>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">JPEG, PNG or WebP, up to 5 MB.</span>
        </div>
        <input ref={input} type="file" accept={ACCEPT} className="sr-only" onChange={onFile} tabIndex={-1} />
      </div>
      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}

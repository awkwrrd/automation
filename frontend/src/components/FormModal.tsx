import { useState } from "react";
import { Field, Input, Modal, Select, useAction } from "./ui";

export interface FieldDef {
  key: string;
  label: string;
  type?: "text" | "number" | "checkbox" | "select" | "password";
  options?: (string | { value: string | number; label: string })[];
  required?: boolean;
  span?: number;
  hint?: string;
  placeholder?: string;
}

/** Generic create/edit dialog driven by a field list. */
export function FormModal<T extends Record<string, unknown>>({ title, fields, initial, onSubmit, onClose, submitLabel = "Save" }: {
  title: string; fields: FieldDef[]; initial: T; onSubmit: (v: T) => Promise<unknown>; onClose: () => void; submitLabel?: string;
}) {
  const [v, setV] = useState<T>(initial);
  const { busy, run } = useAction();
  const missing = fields.some((f) => f.required && (v[f.key] === "" || v[f.key] === null || v[f.key] === undefined));
  const submit = async () => {
    const out: Record<string, unknown> = { ...v };
    fields.forEach((f) => {
      if (f.type === "number") out[f.key] = out[f.key] === "" || out[f.key] === null ? null : Number(out[f.key]);
      else if (f.type !== "checkbox" && out[f.key] === "") out[f.key] = null;
    });
    const r = await run(() => onSubmit(out as T), "Saved");
    if (r !== undefined) onClose();
  };
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || missing} onClick={submit}>{submitLabel}</button>
    </>}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); if (!missing) submit(); }}>
        {fields.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? " *" : ""}`} span={f.span} hint={f.hint}>
            {f.type === "checkbox" ? (
              <label className="check"><input type="checkbox" checked={!!v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.checked })} /> Yes</label>
            ) : f.type === "select" ? (
              <Select value={String(v[f.key] ?? "")} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} options={f.options ?? []} placeholder={f.required ? undefined : "—"} />
            ) : (
              <Input type={f.type ?? "text"} value={String(v[f.key] ?? "")} placeholder={f.placeholder} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />
            )}
          </Field>
        ))}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}

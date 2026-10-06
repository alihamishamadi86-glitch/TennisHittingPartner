"use client";

export function ChipGroup<T extends string>({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: Record<T, string>;
  value: T[];
  onChange: (value: T[]) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium text-zinc-800 dark:text-zinc-200">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {(Object.entries(options) as [T, string][]).map(([key, label]) => {
          const selected = value.includes(key);
          return (
            <label
              key={key}
              className={`cursor-pointer rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                selected
                  ? "border-emerald-600 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                  : "border-zinc-300 text-zinc-700 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300"
              }`}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={selected}
                onChange={() => onChange(selected ? value.filter((v) => v !== key) : [...value, key])}
              />
              {label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

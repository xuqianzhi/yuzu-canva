// A compact dropdown for one setting of a node (the prompt card's bottom row),
// and for a video's length, which two places let you change.
import { VIDEO_SECONDS } from "../api/types";
import { useT } from "../i18n";

export function ParamSelect<V extends string | number>({
  label,
  value,
  options,
  format = String,
  onChange,
}: {
  label: string;
  value: V;
  options: readonly V[];
  format?: (value: V) => string;
  onChange: (value: V) => void;
}) {
  return (
    <select
      aria-label={label}
      title={label}
      value={value}
      onChange={(e) => {
        // Options keep their type: numbers come back as numbers.
        const picked = options.find((v) => String(v) === e.target.value);
        if (picked !== undefined) onChange(picked);
      }}
    >
      {options.map((v) => (
        <option key={v} value={v}>
          {format(v)}
        </option>
      ))}
    </select>
  );
}

/** A video's length in seconds, 4 to 15. */
export function DurationSelect({
  value,
  onChange,
  label,
}: {
  value: number;
  onChange: (seconds: number) => void;
  label: string;
}) {
  const t = useT();
  return (
    <ParamSelect
      label={label}
      value={value}
      options={VIDEO_SECONDS}
      format={(n) => t("seconds", { n })}
      onChange={onChange}
    />
  );
}

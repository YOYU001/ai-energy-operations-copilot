import type { ButtonHTMLAttributes } from "react";

export default function IconButton({
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`rounded-md p-2 hover:bg-foreground/10 ${className}`}
      {...props}
    />
  );
}

import * as React from "react";
import { cn } from "@/lib/utils";

export type AlertVariant = "default" | "destructive";

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
}

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "default", children, ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      className={cn(
        "w-full rounded-lg border p-4 text-sm",
        variant === "destructive"
          ? "bg-red-50 text-red-900 border-red-200"
          : "bg-gray-50 text-gray-900 border-gray-200",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
);
Alert.displayName = "Alert";

export const AlertDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("text-sm", className)} {...props} />
  )
);
AlertDescription.displayName = "AlertDescription"; 

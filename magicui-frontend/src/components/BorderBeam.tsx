// Adapted from Magic UI (MIT): vendor/magicui/apps/www/registry/magicui/border-beam.tsx
import { motion, type MotionStyle } from "motion/react";

interface BorderBeamProps {
  size?: number;
  duration?: number;
  colorFrom?: string;
  colorTo?: string;
  borderWidth?: number;
}

export function BorderBeam({ size = 70, duration = 7, colorFrom = "#7967ff", colorTo = "#3cc9b0", borderWidth = 1 }: BorderBeamProps) {
  return (
    <div className="mui-border-beam" style={{ "--beam-width": `${borderWidth}px` } as React.CSSProperties}>
      <motion.div
        className="mui-border-beam-light"
        style={{ width: size, "--color-from": colorFrom, "--color-to": colorTo, offsetPath: `rect(0 auto auto 0 round ${size}px)` } as MotionStyle}
        initial={{ offsetDistance: "0%" }}
        animate={{ offsetDistance: "100%" }}
        transition={{ repeat: Infinity, ease: "linear", duration }}
      />
    </div>
  );
}

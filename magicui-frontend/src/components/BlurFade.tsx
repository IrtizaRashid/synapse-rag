// Adapted from Magic UI (MIT): vendor/magicui/apps/www/registry/magicui/blur-fade.tsx
import { motion, useReducedMotion, type MotionProps } from "motion/react";
import type { ReactNode } from "react";

interface BlurFadeProps extends MotionProps {
  children: ReactNode;
  className?: string;
  duration?: number;
  delay?: number;
  offset?: number;
}

export function BlurFade({ children, className = "", duration = 0.42, delay = 0, offset = 8, ...props }: BlurFadeProps) {
  const reducedMotion = useReducedMotion();
  return (
    <motion.div
      initial={reducedMotion ? false : { y: -offset, opacity: 0, filter: "blur(6px)" }}
      animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
      transition={{ delay: 0.04 + delay, duration: reducedMotion ? 0 : duration, ease: "easeOut" }}
      className={className}
      {...props}
    >{children}</motion.div>
  );
}

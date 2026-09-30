// Adapted from Magic UI (MIT): vendor/magicui/apps/www/registry/magicui/magic-card.tsx
import { motion, useMotionTemplate, useMotionValue } from "motion/react";
import type { PointerEvent, ReactNode } from "react";

interface MagicCardProps {
  children: ReactNode;
  className?: string;
  gradientSize?: number;
  gradientFrom?: string;
  gradientTo?: string;
}

export function MagicCard({ children, className = "", gradientSize = 180, gradientFrom = "#7967ff", gradientTo = "#3cc9b0" }: MagicCardProps) {
  const mouseX = useMotionValue(-gradientSize);
  const mouseY = useMotionValue(-gradientSize);
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    mouseX.set(event.clientX - rect.left);
    mouseY.set(event.clientY - rect.top);
  };
  const reset = () => { mouseX.set(-gradientSize); mouseY.set(-gradientSize); };

  return (
    <motion.div className={`mui-magic-card ${className}`} onPointerMove={move} onPointerLeave={reset}
      style={{ background: useMotionTemplate`linear-gradient(var(--mui-card-bg) 0 0) padding-box, radial-gradient(${gradientSize}px circle at ${mouseX}px ${mouseY}px, ${gradientFrom}, ${gradientTo}, var(--mui-card-border) 100%) border-box` }}>
      <motion.div className="mui-magic-glow" style={{ background: useMotionTemplate`radial-gradient(${gradientSize}px circle at ${mouseX}px ${mouseY}px, color-mix(in srgb, ${gradientFrom} 15%, transparent), transparent 100%)` }} />
      <div className="mui-magic-content">{children}</div>
    </motion.div>
  );
}

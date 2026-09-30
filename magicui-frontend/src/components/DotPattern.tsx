// Adapted from Magic UI (MIT): vendor/magicui/apps/www/registry/magicui/dot-pattern.tsx
import { useEffect, useId, useMemo, useRef, useState, type SVGProps } from "react";
import { motion } from "motion/react";

interface DotPatternProps extends SVGProps<SVGSVGElement> {
  width?: number;
  height?: number;
  cx?: number;
  cy?: number;
  cr?: number;
  glow?: boolean;
}

export function DotPattern({ width = 24, height = 24, cx = 1, cy = 1, cr = 1, glow = false, className = "", ...props }: DotPatternProps) {
  const id = useId();
  const containerRef = useRef<SVGSVGElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const update = () => {
      const box = containerRef.current?.getBoundingClientRect();
      if (box) setDimensions({ width: box.width, height: box.height });
    };
    update();
    const observer = new ResizeObserver(update);
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const dots = useMemo(() => {
    const cols = Math.ceil(dimensions.width / width);
    const rows = Math.ceil(dimensions.height / height);
    return Array.from({ length: cols * rows }, (_, index) => ({
      x: (index % cols) * width + cx,
      y: Math.floor(index / cols) * height + cy,
      delay: ((index * 17) % 50) / 10,
      duration: 2 + ((index * 13) % 30) / 10,
    }));
  }, [dimensions, width, height, cx, cy]);

  return (
    <svg ref={containerRef} aria-hidden="true" className={`mui-dot-pattern ${className}`} {...props}>
      <defs><radialGradient id={`${id}-gradient`}><stop offset="0%" stopColor="currentColor" /><stop offset="100%" stopColor="currentColor" stopOpacity="0" /></radialGradient></defs>
      {dots.map((dot) => (
        <motion.circle key={`${dot.x}-${dot.y}`} cx={dot.x} cy={dot.y} r={cr} fill={glow ? `url(#${id}-gradient)` : "currentColor"}
          initial={glow ? { opacity: 0.2, scale: 1 } : {}}
          animate={glow ? { opacity: [0.2, 0.75, 0.2], scale: [1, 1.45, 1] } : {}}
          transition={glow ? { duration: dot.duration, repeat: Infinity, delay: dot.delay, ease: "easeInOut" } : {}} />
      ))}
    </svg>
  );
}

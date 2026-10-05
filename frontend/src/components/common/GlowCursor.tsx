import React, { useEffect, useRef } from 'react';

export interface GlowCursorProps {
  color?: string;
  secondaryColor?: string;
  trailLength?: number;
  trailWidth?: number;
  trailTaper?: number;
  followSpeed?: number;
  glowIntensity?: number;
  glowSpread?: number;
  hotspot?: number;
  brightness?: number;
  opacity?: number;
  pulseSpeed?: number;
  noiseStrength?: number;
  idleFade?: boolean;
  idleTimeout?: number;
  fadeDuration?: number;
  blendMode?: GlobalCompositeOperation;
  children?: React.ReactNode;
  className?: string;
}

interface Point {
  x: number;
  y: number;
}

export default function GlowCursor({
  color = '#67E8F9',
  secondaryColor = '#A78BFA',
  trailLength = 40,
  trailWidth = 8,
  trailTaper = 0.8,
  followSpeed = 0.16,
  glowIntensity = 1.9,
  glowSpread = 1.2,
  hotspot = 0.65,
  brightness = 1.25,
  opacity = 1,
  pulseSpeed = 1.1,
  noiseStrength = 0.035,
  idleFade = true,
  idleTimeout = 700,
  fadeDuration = 900,
  blendMode = 'screen',
  children,
  className = '',
}: GlowCursorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const mousePos = useRef<Point>({ x: -100, y: -100 });
  const currentPos = useRef<Point>({ x: -100, y: -100 });
  const trail = useRef<Point[]>([]);
  const lastMoveTime = useRef<number>(Date.now());
  const isInside = useRef<boolean>(false);
  const animFrameId = useRef<number>(0);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let dpr = window.devicePixelRatio || 1;

    const updateSize = () => {
      if (!container || !canvas) return;
      const rect = container.getBoundingClientRect();
      dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    };

    updateSize();
    const resizeObserver = new ResizeObserver(updateSize);
    resizeObserver.observe(container);

    const handlePointerMove = (e: PointerEvent) => {
      if (!container) return;
      const rect = container.getBoundingClientRect();
      mousePos.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };
      if (!isInside.current) {
        currentPos.current = { ...mousePos.current };
        isInside.current = true;
      }
      lastMoveTime.current = Date.now();
    };

    const handlePointerLeave = () => {
      isInside.current = false;
    };

    container.addEventListener('pointermove', handlePointerMove);
    container.addEventListener('pointerleave', handlePointerLeave);

    const startTime = performance.now();

    const render = (now: number) => {
      const elapsed = (now - startTime) / 1000;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.scale(dpr, dpr);

      // Lerp current position toward mouse
      if (isInside.current) {
        currentPos.current.x += (mousePos.current.x - currentPos.current.x) * followSpeed;
        currentPos.current.y += (mousePos.current.y - currentPos.current.y) * followSpeed;

        // Apply organic noise jitter
        const noiseX = (Math.random() - 0.5) * noiseStrength * 20;
        const noiseY = (Math.random() - 0.5) * noiseStrength * 20;

        trail.current.unshift({
          x: currentPos.current.x + noiseX,
          y: currentPos.current.y + noiseY,
        });

        if (trail.current.length > trailLength) {
          trail.current.pop();
        }
      } else {
        if (trail.current.length > 0) {
          trail.current.pop();
        }
      }

      // Idle fade calculation
      let currentOpacity = opacity;
      if (idleFade) {
        const timeSinceMove = Date.now() - lastMoveTime.current;
        if (timeSinceMove > idleTimeout) {
          const fadeProgress = Math.min(1, (timeSinceMove - idleTimeout) / fadeDuration);
          currentOpacity *= 1 - fadeProgress;
        }
      }

      if (trail.current.length > 1 && currentOpacity > 0.01) {
        ctx.save();
        ctx.globalCompositeOperation = blendMode;
        ctx.globalAlpha = currentOpacity;

        const pulse = 1 + Math.sin(elapsed * pulseSpeed * Math.PI * 2) * 0.15;

        // 1. Draw glowing trail segments
        for (let i = 0; i < trail.current.length - 1; i++) {
          const p1 = trail.current[i];
          const p2 = trail.current[i + 1];
          if (!p1 || !p2) continue;
          const progress = i / trail.current.length;
          const segmentWidth = Math.max(1, trailWidth * (1 - progress * trailTaper) * pulse);

          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = i % 2 === 0 ? color : secondaryColor;
          ctx.lineWidth = segmentWidth;
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';
          ctx.shadowColor = color;
          ctx.shadowBlur = 12 * glowIntensity * (1 - progress);
          ctx.stroke();
        }

        // 2. Draw outer ambient glow at the head
        const head = trail.current[0];
        if (head) {
          const glowRadius = Math.max(10, trailWidth * 5 * glowSpread * pulse);
          const gradient = ctx.createRadialGradient(
            head.x,
            head.y,
            0,
            head.x,
            head.y,
            glowRadius
          );
          gradient.addColorStop(0, color);
          gradient.addColorStop(0.4, secondaryColor);
          gradient.addColorStop(1, 'rgba(0,0,0,0)');

          ctx.beginPath();
          ctx.arc(head.x, head.y, glowRadius, 0, Math.PI * 2);
          ctx.fillStyle = gradient;
          ctx.shadowColor = color;
          ctx.shadowBlur = 24 * glowIntensity;
          ctx.fill();

          // 3. Draw bright hotspot core
          const hotspotRadius = Math.max(2, trailWidth * hotspot * pulse);
          ctx.beginPath();
          ctx.arc(head.x, head.y, hotspotRadius, 0, Math.PI * 2);
          ctx.fillStyle = '#FFFFFF';
          ctx.shadowColor = '#FFFFFF';
          ctx.shadowBlur = 10 * brightness;
          ctx.fill();
        }

        ctx.restore();
      }

      animFrameId.current = requestAnimationFrame(render);
    };

    animFrameId.current = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animFrameId.current);
      resizeObserver.disconnect();
      container.removeEventListener('pointermove', handlePointerMove);
      container.removeEventListener('pointerleave', handlePointerLeave);
    };
  }, [
    color,
    secondaryColor,
    trailLength,
    trailWidth,
    trailTaper,
    followSpeed,
    glowIntensity,
    glowSpread,
    hotspot,
    brightness,
    opacity,
    pulseSpeed,
    noiseStrength,
    idleFade,
    idleTimeout,
    fadeDuration,
    blendMode,
  ]);

  return (
    <div
      ref={containerRef}
      className={`relative w-full overflow-hidden ${className}`}
      style={{ position: 'relative' }}
    >
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 z-20"
      />
      <div className="relative z-10 w-full h-full">{children}</div>
    </div>
  );
}

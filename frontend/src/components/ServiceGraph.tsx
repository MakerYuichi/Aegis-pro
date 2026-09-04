import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { type Incident, type Service } from '../utils/api';
import { motion } from 'framer-motion';

interface ServiceGraphProps {
  services: Service[];
  incidents: Incident[];
  onNodeClick?: (serviceName: string) => void;
}

interface TooltipData {
  serviceName: string;
  hasIncident: boolean;
  incidentCount: number;
  severity: string | null;
  dependencies: string[];
  isCritical: boolean;
}

export function ServiceGraph({ services, incidents, onNodeClick }: ServiceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 });
  
  useEffect(() => {
    if (!svgRef.current || !services.length) return;

    const width = 600;
    const height = 400;

    // Clear previous
    d3.select(svgRef.current).selectAll('*').remove();

    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .style('background', 'transparent');

    // Build nodes and links from service dependencies
    const nodes = services.map(s => ({ 
      id: s.name, 
      critical: s.is_critical || false,
      hasIncident: incidents.some(i => i.service_name === s.name),
      incidentCount: incidents.filter(i => i.service_name === s.name).length,
      severity: incidents.find(i => i.service_name === s.name)?.severity || null,
      dependencies: s.dependencies || []
    }));
    
    const links = services.flatMap(s =>
      (s.dependencies || []).map(d => ({ 
        source: s.name, 
        target: d 
      }))
    );

    // Filter out links where target doesn't exist
    const validLinks = links.filter(l => 
      nodes.some(n => n.id === l.source) && nodes.some(n => n.id === l.target)
    );

    const simulation = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(validLinks).id((d: any) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(40));

    // Links
    const link = svg.append('g')
      .selectAll('line')
      .data(validLinks)
      .enter()
      .append('line')
      .attr('stroke', '#94A3B8')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 2);

    // Nodes
    const nodeGroup = svg.append('g')
      .selectAll('g')
      .data(nodes)
      .enter()
      .append('g')
      .style('cursor', 'pointer')
      .on('click', (_event, d: any) => {
        if (onNodeClick) onNodeClick(d.id);
      })
      .on('mouseenter', (_event, d: any) => {
        setTooltip({
          serviceName: d.id,
          hasIncident: d.hasIncident,
          incidentCount: d.incidentCount,
          severity: d.severity,
          dependencies: d.dependencies,
          isCritical: d.critical
        });
      })
      .on('mousemove', (event) => {
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect) {
          setTooltipPosition({
            x: event.clientX - rect.left + 10,
            y: event.clientY - rect.top + 10
          });
        }
      })
      .on('mouseleave', () => {
        setTooltip(null);
      })
      .call(d3.drag<any, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
      );

    nodeGroup.append('circle')
      .attr('r', (d: any) => d.critical ? 28 : 22)
      .attr('fill', (d: any) => {
        if (d.severity === 'P0') return '#DC2626';
        if (d.severity === 'P1') return '#EA580C';
        if (d.hasIncident) return '#D97706';
        return '#3B82F6';
      })
      .attr('stroke', '#fff')
      .attr('stroke-width', 3)
      .attr('filter', 'drop-shadow(0 4px 6px rgba(0,0,0,0.3))')
      .transition()
      .duration(200)
      .attr('r', (d: any) => {
        const baseR = d.critical ? 28 : 22;
        return tooltip?.serviceName === d.id ? baseR + 4 : baseR;
      });

    nodeGroup.append('text')
      .text((d: any) => d.id)
      .attr('text-anchor', 'middle')
      .attr('dy', 5)
      .attr('font-size', 10)
      .attr('fill', '#fff')
      .attr('font-weight', 'bold')
      .style('text-shadow', '0 1px 3px rgba(0,0,0,0.5)');

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      nodeGroup
        .attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };

  }, [services, incidents, onNodeClick]);

  return (
    <div ref={containerRef} className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-4 backdrop-blur-sm relative">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-light-text dark:text-dark-text">Service Dependency Graph</h3>
        <div className="flex gap-4 text-xs text-light-muted dark:text-dark-muted">
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-severity-critical mr-1"></span>P0</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-severity-high mr-1"></span>P1</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-severity-medium mr-1"></span>Has Incident</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-brand-primary mr-1"></span>Healthy</span>
        </div>
      </div>
      <svg ref={svgRef} className="w-full h-96"></svg>
      
      {tooltip && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="absolute bg-white dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg shadow-xl p-4 z-10 max-w-xs"
          style={{
            left: tooltipPosition.x,
            top: tooltipPosition.y,
          }}
        >
          <h4 className="font-semibold text-light-text dark:text-dark-text mb-2">{tooltip.serviceName}</h4>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-light-muted dark:text-dark-muted">Status:</span>
              <span className={tooltip.hasIncident ? 'text-severity-critical' : 'text-brand-success'}>
                {tooltip.hasIncident ? 'Incident' : 'Healthy'}
              </span>
            </div>
            {tooltip.hasIncident && (
              <>
                <div className="flex justify-between">
                  <span className="text-light-muted dark:text-dark-muted">Incidents:</span>
                  <span className="text-light-text dark:text-dark-text">{tooltip.incidentCount}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-light-muted dark:text-dark-muted">Severity:</span>
                  <span className={`font-medium ${
                    tooltip.severity === 'P0' ? 'text-severity-critical' :
                    tooltip.severity === 'P1' ? 'text-severity-high' :
                    'text-brand-warning'
                  }`}>
                    {tooltip.severity}
                  </span>
                </div>
              </>
            )}
            <div className="flex justify-between">
              <span className="text-light-muted dark:text-dark-muted">Critical:</span>
              <span className={tooltip.isCritical ? 'text-severity-critical' : 'text-light-text dark:text-dark-muted'}>
                {tooltip.isCritical ? 'Yes' : 'No'}
              </span>
            </div>
            {tooltip.dependencies.length > 0 && (
              <div>
                <span className="text-light-muted dark:text-dark-muted block mb-1">Dependencies:</span>
                <div className="flex flex-wrap gap-1">
                  {tooltip.dependencies.map((dep) => (
                    <span key={dep} className="text-xs bg-light-surface dark:bg-dark-surface px-2 py-0.5 rounded">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </div>
  );
}

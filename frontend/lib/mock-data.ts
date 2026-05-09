import type { Agent, Project, AgentResult } from './types'

export const AVAILABLE_AGENTS: Agent[] = [
  {
    id: 'agent-analyst',
    name: 'Business Analyst',
    model: 'GPT-4o',
    role: 'analyst',
    description: 'Requirements, architecture, strategy',
    color: '#3b82f6',
  },
  {
    id: 'agent-designer',
    name: 'UI/UX Designer',
    model: 'Claude 3.5',
    role: 'designer',
    description: 'Visual design, wireframes, UX',
    color: '#8b5cf6',
  },
  {
    id: 'agent-frontend',
    name: 'Frontend Dev',
    model: 'GPT-4o',
    role: 'frontend',
    description: 'React, HTML/CSS, implementation',
    color: '#10b981',
  },
  {
    id: 'agent-backend',
    name: 'Backend Dev',
    model: 'Llama-3',
    role: 'backend',
    description: 'API, database, infrastructure',
    color: '#06b6d4',
  },
  {
    id: 'agent-copywriter',
    name: 'Copywriter',
    model: 'GPT-4o',
    role: 'copywriter',
    description: 'Content, marketing copy, SEO',
    color: '#f59e0b',
  },
  {
    id: 'agent-devops',
    name: 'DevOps Engineer',
    model: 'Mistral',
    role: 'devops',
    description: 'Deployment, CI/CD, monitoring',
    color: '#ef4444',
  },
]

export const MOCK_PROJECTS: Project[] = [
  {
    id: 'proj-1',
    name: 'E-commerce Website',
    description: 'Online store for organic products with payment integration and inventory management',
    agents: [
      AVAILABLE_AGENTS[0],
      AVAILABLE_AGENTS[1],
      AVAILABLE_AGENTS[2],
      AVAILABLE_AGENTS[4],
    ],
    files: [
      { id: 'f1', name: 'project-brief.pdf', size: '2.3 MB', type: 'pdf', category: 'brief', uploadedAt: '2026-01-15' },
      { id: 'f2', name: 'homepage-mockup.png', size: '1.1 MB', type: 'image', category: 'mockup', uploadedAt: '2026-01-15' },
      { id: 'f3', name: 'brand-guidelines.pdf', size: '4.5 MB', type: 'pdf', category: 'reference', uploadedAt: '2026-01-16' },
    ],
    messages: [
      { id: 'm1', agentId: 'user', content: 'Let\'s start working on the e-commerce project. I need a modern, clean design.', timestamp: '10:00 AM' },
      { id: 'm2', agentId: 'agent-analyst', content: 'I\'ve reviewed the brief. Here are the key requirements:\n\n1. **Product catalog** with categories and filters\n2. **Shopping cart** with persistent state\n3. **Checkout flow** with Stripe integration\n4. **User accounts** with order history\n5. **Admin panel** for inventory management\n\nShould I create a detailed technical specification?', timestamp: '10:02 AM' },
      { id: 'm3', agentId: 'agent-designer', content: 'Based on the brand guidelines, I suggest a minimalist approach with:\n\n- Clean white backgrounds with organic green accents\n- Large product imagery\n- Sans-serif typography (Inter or similar)\n- Rounded corners for a friendly feel\n\nI can start wireframing the homepage and product pages.', timestamp: '10:05 AM' },
      { id: 'm4', agentId: 'user', content: '@designer @frontend let\'s discuss the homepage layout', timestamp: '10:10 AM', isGroupDiscussion: true, discussionId: 'disc-1' },
      { id: 'm5', agentId: 'agent-designer', content: 'For the homepage, I recommend:\n\n1. **Hero section** with featured products carousel\n2. **Category grid** with hover effects\n3. **Best sellers** section\n4. **Newsletter signup** with discount offer\n\nThis follows e-commerce best practices for conversion.', timestamp: '10:12 AM', isGroupDiscussion: true, discussionId: 'disc-1' },
      { id: 'm6', agentId: 'agent-frontend', content: 'I can implement that with Next.js and Tailwind. For the carousel, I\'d suggest using Embla for smooth animations. The category grid can use CSS Grid with `aspect-ratio` for consistent sizing.\n\n```tsx\n<div className="grid grid-cols-2 md:grid-cols-4 gap-4">\n  {categories.map(cat => (\n    <CategoryCard key={cat.id} {...cat} />\n  ))}\n</div>\n```\n\nI\'ll set up the project structure today.', timestamp: '10:15 AM', isGroupDiscussion: true, discussionId: 'disc-1' },
    ],
    createdAt: '2026-01-15',
    updatedAt: '2026-01-16',
  },
  {
    id: 'proj-2',
    name: 'Mobile App Landing',
    description: 'Landing page for fitness app with app store links and feature showcase',
    agents: [
      AVAILABLE_AGENTS[1],
      AVAILABLE_AGENTS[4],
      AVAILABLE_AGENTS[2],
    ],
    files: [
      { id: 'f4', name: 'app-screenshots.zip', size: '8.2 MB', type: 'image', category: 'mockup', uploadedAt: '2026-01-10' },
      { id: 'f5', name: 'competitor-analysis.pdf', size: '1.8 MB', type: 'pdf', category: 'reference', uploadedAt: '2026-01-10' },
      { id: 'f6', name: 'brand-assets.fig', size: '3.2 MB', type: 'figma', category: 'reference', uploadedAt: '2026-01-11' },
      { id: 'f7', name: 'copy-draft.docx', size: '45 KB', type: 'doc', category: 'brief', uploadedAt: '2026-01-12' },
      { id: 'f8', name: 'seo-keywords.txt', size: '12 KB', type: 'text', category: 'reference', uploadedAt: '2026-01-12' },
    ],
    messages: [
      { id: 'm7', agentId: 'user', content: 'We need a high-converting landing page for our fitness app launch.', timestamp: '9:00 AM' },
      { id: 'm8', agentId: 'agent-copywriter', content: 'I\'ll craft compelling copy that highlights the app\'s unique features. Key messages:\n\n- **Personalized workouts** that adapt to your progress\n- **AI-powered form correction** using your phone camera\n- **Community challenges** to stay motivated\n\nWhat\'s our target audience demographic?', timestamp: '9:03 AM' },
    ],
    createdAt: '2026-01-10',
    updatedAt: '2026-01-12',
  },
]

export const MOCK_RESULTS: AgentResult[] = [
  {
    id: 'res-1',
    agentId: 'agent-analyst',
    title: 'Technical Architecture Document',
    category: 'architecture',
    content: '# E-commerce Architecture\n\n## Tech Stack\n- **Frontend**: Next.js 14 with App Router\n- **Styling**: Tailwind CSS\n- **Database**: PostgreSQL with Prisma ORM\n- **Auth**: NextAuth.js\n- **Payments**: Stripe\n- **Hosting**: Vercel\n\n## Key Features\n1. Server-side rendering for SEO\n2. Edge caching for product pages\n3. Real-time inventory updates\n4. Webhook integration for order processing',
    createdAt: '2026-01-16',
  },
  {
    id: 'res-2',
    agentId: 'agent-designer',
    title: 'Homepage Wireframe',
    category: 'design',
    content: '# Homepage Layout\n\n## Sections\n1. **Navigation** - Sticky header with search, cart, account\n2. **Hero** - Full-width carousel with CTA buttons\n3. **Categories** - 4-column grid with hover effects\n4. **Featured Products** - Horizontal scroll on mobile\n5. **Testimonials** - Customer reviews carousel\n6. **Footer** - Links, newsletter, social media',
    createdAt: '2026-01-16',
  },
  {
    id: 'res-3',
    agentId: 'agent-frontend',
    title: 'Component Library Setup',
    category: 'code',
    content: '```tsx\n// components/ui/ProductCard.tsx\nexport function ProductCard({ product }: { product: Product }) {\n  return (\n    <div className="group relative rounded-lg border p-4 hover:shadow-lg">\n      <Image\n        src={product.image}\n        alt={product.name}\n        className="aspect-square object-cover"\n      />\n      <h3 className="mt-2 font-medium">{product.name}</h3>\n      <p className="text-muted-foreground">${product.price}</p>\n      <Button className="mt-2 w-full">Add to Cart</Button>\n    </div>\n  )\n}\n```',
    createdAt: '2026-01-16',
  },
  {
    id: 'res-4',
    agentId: 'agent-copywriter',
    title: 'Homepage Copy',
    category: 'content',
    content: '# Homepage Copy\n\n## Hero Section\n**Headline**: "Fresh, Organic, Delivered"\n**Subheadline**: "Discover premium organic products sourced directly from local farms"\n**CTA**: "Shop Now" | "Learn Our Story"\n\n## Value Props\n- 100% Certified Organic\n- Free Delivery Over $50\n- Sustainable Packaging\n- Support Local Farmers',
    createdAt: '2026-01-16',
  },
]

export const AGENT_RESPONSES: Record<string, string[]> = {
  'agent-analyst': [
    'I\'ve analyzed the requirements. Here are my recommendations...',
    'Based on the project scope, we should prioritize these features...',
    'Let me break down the technical considerations for this approach...',
  ],
  'agent-designer': [
    'I suggest we go with a clean, modern aesthetic that emphasizes...',
    'Looking at the brand guidelines, I recommend these visual elements...',
    'Here\'s my proposed layout structure for better user experience...',
  ],
  'agent-frontend': [
    'I can implement this using React with the following component structure...',
    'For optimal performance, I recommend using server components here...',
    'This can be achieved with a combination of CSS Grid and Flexbox...',
  ],
  'agent-backend': [
    'I\'ll set up the API endpoints with proper authentication middleware...',
    'For the database schema, I suggest the following structure...',
    'We should implement caching at this layer for better performance...',
  ],
  'agent-copywriter': [
    'I\'ve drafted compelling copy that aligns with your brand voice...',
    'Here are several headline options to test for conversion...',
    'The key messaging should focus on these customer pain points...',
  ],
  'agent-devops': [
    'I\'ll configure the CI/CD pipeline with automated testing...',
    'For deployment, I recommend a blue-green strategy to minimize downtime...',
    'Monitoring should include these key metrics and alerts...',
  ],
}

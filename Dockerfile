FROM node:20-alpine

WORKDIR /app

# Copy root package files
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/

# Install dependencies
RUN npm ci

# Copy project files
COPY . .

# Build args for Next.js build-time static environment variable embedding
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Build Next.js web app
RUN npm run build --workspace=apps/web

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "run", "start", "--workspace=apps/web"]

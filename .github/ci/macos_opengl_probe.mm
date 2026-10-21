#define GL_SILENCE_DEPRECATION
#import <Cocoa/Cocoa.h>
#import <OpenGL/gl.h>

#include <cstdio>

bool probe(const char * name, bool multisample, bool accelerated)
{
  NSOpenGLPixelFormatAttribute attributes[24];
  int count = 0;
  attributes[count++] = NSOpenGLPFAOpenGLProfile;
  attributes[count++] = NSOpenGLProfileVersionLegacy;
  attributes[count++] = NSOpenGLPFAColorSize;
  attributes[count++] = 24;
  attributes[count++] = NSOpenGLPFADepthSize;
  attributes[count++] = 24;
  attributes[count++] = NSOpenGLPFADoubleBuffer;
  if (accelerated) {
    attributes[count++] = NSOpenGLPFAAccelerated;
  }
  if (multisample) {
    attributes[count++] = NSOpenGLPFAMultisample;
    attributes[count++] = NSOpenGLPFASampleBuffers;
    attributes[count++] = 1;
    attributes[count++] = NSOpenGLPFASamples;
    attributes[count++] = 4;
  }
  attributes[count] = 0;
  NSOpenGLPixelFormat * format = [[NSOpenGLPixelFormat alloc] initWithAttributes:attributes];
  NSOpenGLContext * context = format ?
    [[NSOpenGLContext alloc] initWithFormat:format shareContext:nil] : nil;
  [context makeCurrentContext];
  const GLubyte * version = context ? glGetString(GL_VERSION) : nullptr;
  const GLubyte * renderer = context ? glGetString(GL_RENDERER) : nullptr;
  std::printf("probe=%s format=%p context=%p version=%s renderer=%s\n", name,
    static_cast<void *>(format), static_cast<void *>(context),
    version ? reinterpret_cast<const char *>(version) : "unavailable",
    renderer ? reinterpret_cast<const char *>(renderer) : "unavailable");
  std::fflush(stdout);
  const bool available = version != nullptr;
  [NSOpenGLContext clearCurrentContext];
  [context release];
  [format release];
  return available;
}

int main()
{
  @autoreleasepool {
    [NSApplication sharedApplication];
    const bool available = probe("default", false, false);
    probe("fsaa4", true, false);
    probe("accelerated", false, true);
    return available ? 0 : 1;
  }
}

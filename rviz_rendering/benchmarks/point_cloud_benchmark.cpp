// Copyright (c) 2026, John C. Furey
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
//    * Redistributions of source code must retain the above copyright
//      notice, this list of conditions and the following disclaimer.
//
//    * Redistributions in binary form must reproduce the above copyright
//      notice, this list of conditions and the following disclaimer in the
//      documentation and/or other materials provided with the distribution.
//
//    * Neither the name of the copyright holder nor the names of its
//      contributors may be used to endorse or promote products derived from
//      this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.


#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <QApplication>  // NOLINT
#include <OgreLogManager.h>  // NOLINT
#include <OgreRenderSystem.h>  // NOLINT
#include <OgreRenderSystemCapabilities.h>  // NOLINT
#include <OgreRoot.h>  // NOLINT

#include "rviz_rendering/objects/point_cloud.hpp"
#include "rviz_rendering/render_window.hpp"
#include "rviz_rendering/render_system.hpp"

using Clock = std::chrono::steady_clock;
using rviz_rendering::RenderWindowOgreAdapter;

// Linux resident memory, not a count of live allocations or GPU memory.
// Other platforms report -1 and can use an external memory profiler.
int64_t residentKiB()
{
  std::ifstream status("/proc/self/status");
  std::string key;
  while (status >> key) {
    if (key == "VmRSS:") {
      int64_t value = -1;
      status >> value;
      return value;
    }
    std::string rest;
    std::getline(status, rest);
  }
  return -1;
}

double milliseconds(Clock::time_point start, Clock::time_point end)
{
  return std::chrono::duration<double, std::milli>(end - start).count();
}

int main(int argc, char ** argv)
{
  QApplication app(argc, argv);
  if (argc != 7) {
    std::cerr << "Usage: point_cloud_benchmark POINTS SAMPLES WARMUP RETAINED_BATCHES "
              << "points|boxes render|upload\n";
    return 2;
  }
  try {
    const auto count = std::stoull(argv[1]);
    const auto samples = std::stoull(argv[2]);
    const auto warmup = std::stoull(argv[3]);
    const auto batches = std::stoull(argv[4]);
    const std::string mode = argv[5];
    const std::string operation = argv[6];
    if (!count || !samples || !batches || warmup < batches ||
      batches > std::numeric_limits<uint32_t>::max() ||
      count > std::numeric_limits<uint32_t>::max() / batches ||
      samples > std::numeric_limits<unsigned int>::max() ||
      warmup > std::numeric_limits<unsigned int>::max() ||
      (mode != "points" && mode != "boxes") ||
      (operation != "render" && operation != "upload"))
    {
      throw std::invalid_argument("Invalid workload or insufficient warmup");
    }
    // Activate the atomic shared_ptr path used by multithreaded ROS processes.
    std::thread([] {}).join();
    auto * logs = new Ogre::LogManager();
    logs->createLog("", false, false, true);
    std::unique_ptr<rviz_rendering::RenderSystem> system(rviz_rendering::RenderSystem::get());
    const auto * caps = system->getOgreRoot()->getRenderSystem()->getCapabilities();
    std::cout << "DEVICE " << caps->getDeviceName() << '\n';
    std::cout << "QT " << qVersion() << '\n';
    std::cout << "DRIVER " << caps->getDriverVersion().toString() << '\n';
    {
      rviz_rendering::RenderWindow window;
      window.resize(640, 480);
      window.initialize();
      RenderWindowOgreAdapter::setOgreCameraPosition(&window, Ogre::Vector3(0, 0, 4));
      RenderWindowOgreAdapter::setOgreCameraOrientation(&window, Ogre::Quaternion::IDENTITY);
      if (operation == "render") {
        window.show();
        app.processEvents();
      }
      std::cout << "SCALE " << window.devicePixelRatio() << '\n';
      std::vector<rviz_rendering::PointCloud::Point> points(count);
      for (size_t i = 0; i < points.size(); ++i) {
        points[i].position = Ogre::Vector3(
          static_cast<float>(i % 1000) / 500 - 1,
          static_cast<float>((i / 1000) % 1000) / 500 - 1,
          static_cast<float>(i / 1000000) / 10);
        points[i].color = Ogre::ColourValue(0.2f, 0.4f, 0.6f, 1.0f);
      }
      rviz_rendering::PointCloud cloud;
      cloud.setRenderMode(mode == "boxes" ? rviz_rendering::PointCloud::RM_BOXES :
        rviz_rendering::PointCloud::RM_POINTS);
      cloud.setDimensions(0.005f, 0.005f, 0.005f);
      auto * node = RenderWindowOgreAdapter::getSceneManager(&window)->getRootSceneNode();
      node->attachObject(&cloud);
      std::cout << "VERTICES_PER_POINT " << cloud.getVerticesPerPoint() << '\n';
      std::cout << "COLUMNS sample,update_ms,render_call_ms,rss_kib\n";
      for (uint64_t frame = 0; frame < warmup + samples; ++frame) {
        app.processEvents();
        if (operation == "render" && frame >= warmup && !window.isExposed()) {
          throw std::runtime_error("The benchmark window must remain exposed while rendering");
        }
        points.front().position.z = static_cast<float>(frame % 100) / 100;
        const auto start = Clock::now();
        if (batches == 1) {
          cloud.clearAndRemoveAllPoints();
        } else if (frame >= batches) {
          cloud.popPoints(static_cast<uint32_t>(count));
        }
        cloud.addPoints(points.begin(), points.end());
        const auto uploaded = Clock::now();
        if (operation == "render") {
          window.render();
        }
        const auto rendered = Clock::now();
        if (frame >= warmup) {
          std::cout << "SAMPLE " << frame - warmup << ',' << milliseconds(start, uploaded)
                    << ',' << milliseconds(uploaded, rendered) << ',' << residentKiB() << '\n';
        }
      }
      // getPoints() copies the vector; keep that allocation outside the samples.
      const auto retained = cloud.getPoints().size();
      std::cout << "RETAINED_POINTS " << retained << std::endl;
      if (retained != count * batches) {
        throw std::runtime_error("Unexpected retained point count");
      }
      node->detachObject(&cloud);
    }
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
